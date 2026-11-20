import asyncio
import time
import logging
from typing import Optional
from config import CONFIG

logger = logging.getLogger("oxalpha.turnstile")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>oxalpha-Turnstile</title>
    <script src="https://challenges.cloudflare.com/turnstile/v0/api.js?onload=onloadTurnstileCallback" async="" defer=""></script>
</head>
<body>
    <!-- cf turnstile -->
</body>
</html>"""

class TurnstileManager:
    def __init__(self):
        self._solve_lock = asyncio.Lock()
        self._cached_token: Optional[str] = None
        self._token_timestamp: float = 0
        self._browser = None
        self._warm_page = None
        self._warm_context = None

    async def get_valid_token(self, force_refresh: bool = False) -> Optional[str]:
        """
        Returns a cached token if within 180s, or solves fresh.
        """
        async with self._solve_lock:
            now = time.time()
            if not force_refresh and self._cached_token and (now - self._token_timestamp < 180):
                logger.info(f"Using cached Turnstile token ({round(now - self._token_timestamp)}s old)")
                return self._cached_token

            # External solver URL check
            if CONFIG.turnstile_solver_url:
                try:
                    import httpx
                    async with httpx.AsyncClient(timeout=30) as client:
                        resp = await client.get(
                            CONFIG.turnstile_solver_url,
                            params={"url": CONFIG.turnstile_url, "sitekey": CONFIG.turnstile_sitekey, "action": CONFIG.turnstile_action}
                        )
                        if resp.status_code in (200, 202):
                            data = resp.json()
                            token = data.get("value") or data.get("token")
                            if token:
                                self._cached_token = token
                                self._token_timestamp = now
                                return token
                except Exception as e:
                    logger.warning(f"External Turnstile solver failed: {e}. Falling back to Camoufox...")

            token = await self._solve_camoufox()
            if token:
                self._cached_token = token
                self._token_timestamp = now
            return token

    async def _solve_camoufox(self) -> Optional[str]:
        start_time = time.time()
        logger.info(f"Starting Turnstile solve for {CONFIG.turnstile_url}")

        try:
            from camoufox.async_api import AsyncCamoufox
            from camoufox import DefaultAddons
        except ImportError:
            logger.error("Camoufox is not installed. Install with: pip install camoufox")
            return None

        px = None
        if CONFIG.proxy:
            from urllib.parse import urlparse
            parsed = urlparse(CONFIG.proxy if "//" in CONFIG.proxy else f"http://{CONFIG.proxy}")
            px = {"server": f"http://{parsed.hostname}:{parsed.port or 80}"}
            if parsed.username:
                px["username"] = parsed.username
                px["password"] = parsed.password or ""

        browser = None
        try:
            browser = await AsyncCamoufox(
                headless=True,
                exclude_addons=[DefaultAddons.UBO],
                proxy=px
            ).start()
            context = await browser.new_context()
            page = await context.new_page()

            url = CONFIG.turnstile_url
            url_with_slash = url if url.endswith("/") else url + "/"
            turnstile_div = (
                f'<div class="cf-turnstile" style="background:white;" data-sitekey="{CONFIG.turnstile_sitekey}"'
                + (f' data-action="{CONFIG.turnstile_action}"' if CONFIG.turnstile_action else "")
                + "></div>"
            )
            page_data = HTML_TEMPLATE.replace("<!-- cf turnstile -->", turnstile_div)

            async def route_handler(route):
                await route.fulfill(body=page_data, status=200, content_type="text/html")

            await page.route(url_with_slash, route_handler)
            await page.goto(url_with_slash, wait_until="domcontentloaded", timeout=20000)

            try:
                await page.eval_on_selector("//div[@class='cf-turnstile']", "el => el.style.width = '70px'")
            except Exception:
                pass

            for _ in range(60):
                try:
                    val = await page.input_value("[name=cf-turnstile-response]", timeout=400)
                    if val and len(val) > 10:
                        elapsed = round(time.time() - start_time, 2)
                        logger.info(f"Turnstile solved successfully in {elapsed}s (token length: {len(val)})")
                        return val
                    loc = page.locator("//div[@class='cf-turnstile']")
                    if await loc.count() > 0:
                        try:
                            await loc.click(timeout=400)
                        except Exception:
                            pass
                except Exception:
                    pass
                await asyncio.sleep(0.4)

            # Fallback to real page
            logger.warning("Turnstile route mode timed out. Trying real page...")
            try:
                await page.unroute_all()
            except Exception:
                pass
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(2.0)

            for _ in range(30):
                try:
                    val = await page.input_value("[name=cf-turnstile-response]", timeout=500)
                    if val and len(val) > 10:
                        elapsed = round(time.time() - start_time, 2)
                        logger.info(f"Turnstile solved via real page in {elapsed}s")
                        return val
                except Exception:
                    pass
                await asyncio.sleep(0.5)

            return None
        except Exception as e:
            logger.error(f"Error solving Turnstile: {e}")
            return None
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

turnstile_manager = TurnstileManager()

async def get_turnstile_token(force_refresh: bool = False) -> Optional[str]:
    return await turnstile_manager.get_valid_token(force_refresh=force_refresh)
