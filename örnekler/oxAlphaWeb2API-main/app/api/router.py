from fastapi import APIRouter
from app.api.v1 import chat, models

api_v1_router = APIRouter(prefix="/v1")
api_v1_router.include_router(models.router, tags=["Models"])
api_v1_router.include_router(chat.router, tags=["Chat"])
