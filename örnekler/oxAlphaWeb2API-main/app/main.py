import logging
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import set_global_provider
from app.api.router import api_v1_router
from app.config import get_settings
from app.providers.oxalpha import OxAlphaProvider
from app.services.rate_limiter import GatewayRateLimiter
from app.services.transport import HTTPTransportPool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("oxalpha-gateway")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan manager for resource allocation and graceful shutdown."""
    settings = get_settings()
    logger.info("Initializing HTTP transport and OxAlpha provider...")
    transport = HTTPTransportPool(settings)
    rate_limiter = GatewayRateLimiter(
        max_concurrent=settings.max_concurrent_requests,
        requests_per_minute=settings.rate_limit_per_minute,
    )
    provider = OxAlphaProvider(
        settings=settings,
        transport=transport,
        rate_limiter=rate_limiter,
    )
    set_global_provider(provider)
    app.state.transport = transport
    app.state.provider = provider
    app.state.rate_limiter = rate_limiter

    yield

    logger.info("Shutting down HTTP transport pool...")
    await transport.aclose()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="OxAlpha OpenAI Gateway",
        description="Clean-room production proxy translating OpenAI API requests to OxAlpha web protocol",
        version=settings.app_version,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Middleware: X-Request-ID propagation
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:16]}"
        request.state.request_id = request_id
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # OpenAI-compliant error formatting
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        err_type = "invalid_request_error"
        if exc.status_code == 401:
            err_type = "authentication_error"
        elif exc.status_code == 429:
            err_type = "rate_limit_error"
        elif exc.status_code >= 500:
            err_type = "api_error"

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "message": str(exc.detail),
                    "type": err_type,
                    "param": None,
                    "code": exc.status_code,
                }
            },
            headers={"X-Request-ID": getattr(request.state, "request_id", "")},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        # Extract messages
        errors = exc.errors()
        messages = []
        is_bad_request = False
        for err in errors:
            msg = err.get("msg", "")
            loc = " -> ".join(str(l) for l in err.get("loc", []))
            messages.append(f"{loc}: {msg}")
            # If tool validation or unfulfillable feature failed, treat as 400 Bad Request
            if "not supported" in msg.lower():
                is_bad_request = True

        status_code = status.HTTP_400_BAD_REQUEST if is_bad_request else status.HTTP_422_UNPROCESSABLE_ENTITY
        return JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "message": "; ".join(messages),
                    "type": "invalid_request_error",
                    "param": None,
                    "code": status_code,
                }
            },
            headers={"X-Request-ID": getattr(request.state, "request_id", "")},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled gateway exception: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "message": "Internal gateway error",
                    "type": "api_error",
                    "param": None,
                    "code": 500,
                }
            },
            headers={"X-Request-ID": getattr(request.state, "request_id", "")},
        )

    @app.get("/health", tags=["Health"])
    async def health_check():
        return {"status": "ok"}

    @app.get("/chat", tags=["UI"], include_in_schema=False)
    async def chat_ui():
        from fastapi.responses import FileResponse
        import os
        ui_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test_chat.html")
        return FileResponse(ui_path, media_type="text/html")

    @app.get("/", tags=["Root"])
    async def root():
        return {
            "name": "OxAlpha OpenAI Gateway",
            "version": settings.app_version,
            "status": "online",
            "ui": "/chat",
            "docs": "/docs",
        }

    app.include_router(api_v1_router)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
