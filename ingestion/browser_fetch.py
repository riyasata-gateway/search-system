"""Shared headless-browser fetch for connectors that need JS rendering or must
pass bot-walls (AWS WAF / Cloudflare interstitials) that block plain httpx.

Plenty of public review sites (Trustpilot, Influenster, JS-widget pharmacies)
return 403/interstitials to a raw HTTP client but render full review data in a
real browser. This wraps Playwright/Chromium behind a small async session a
connector opens once and reuses across many page fetches.

Usage:
    async with BrowserSession() as bs:
        html = await bs.html(url, wait_selector="article")
        data = await bs.next_data(url)        # parsed __NEXT_DATA__ JSON
"""
from __future__ import annotations

import json
from typing import Optional

from core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
# Don't waste bandwidth on assets we never parse — big speed-up over a full load.
_BLOCK_TYPES = {"image", "media", "font"}


def playwright_available() -> bool:
    """True iff the Playwright package and a Chromium binary are present.

    Filesystem check (not `sync_playwright`) so it's safe to call from inside a
    running asyncio loop — the sync API raises there and would falsely report
    "unavailable".
    """
    import glob
    import os
    try:
        import playwright  # noqa: F401
    except Exception:
        return False
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or os.path.expanduser(
        "~/.cache/ms-playwright")
    return bool(glob.glob(os.path.join(base, "chromium*", "chrome-linux*", "chrome")))


class BrowserSession:
    def __init__(self, locale: str = "fr-BE", user_agent: str = DEFAULT_UA,
                 block_assets: bool = True):
        self._locale = locale
        self._ua = user_agent
        self._block_assets = block_assets
        self._pw = None
        self._browser = None
        self._ctx = None

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        self._ctx = await self._browser.new_context(user_agent=self._ua, locale=self._locale)
        if self._block_assets:
            await self._ctx.route(
                "**/*",
                lambda route: (
                    route.abort() if route.request.resource_type in _BLOCK_TYPES
                    else route.continue_()
                ),
            )
        return self

    async def __aexit__(self, *exc):
        try:
            if self._browser:
                await self._browser.close()
        finally:
            if self._pw:
                await self._pw.stop()

    async def html(self, url: str, *, wait_selector: Optional[str] = None,
                   wait_ms: int = 3000, timeout: int = 30000) -> Optional[str]:
        """Return fully-rendered HTML, or None on failure. Waits for the SPA to
        paint (a selector if given, else a fixed settle delay)."""
        page = await self._ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=timeout)
                except Exception:
                    pass  # selector may be absent (no reviews) — return what rendered
            await page.wait_for_timeout(wait_ms)
            return await page.content()
        except Exception as exc:  # noqa: BLE001
            logger.warning("browser_fetch_failed", url=url, error=str(exc))
            return None
        finally:
            await page.close()

    async def next_data(self, url: str, *, wait_selector: Optional[str] = None,
                        wait_ms: int = 2500, timeout: int = 30000) -> Optional[dict]:
        """Parse a Next.js `#__NEXT_DATA__` blob (Trustpilot et al.) into a dict.

        `wait_selector` should be a real-page element (e.g. "article") so we wait
        past any WAF interstitial — which JS-redirects to the real page — before
        reading the data blob."""
        page = await self._ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=timeout)
                except Exception:
                    pass
            await page.wait_for_timeout(wait_ms)
            if await page.locator("#__NEXT_DATA__").count() == 0:
                return None
            raw = await page.locator("#__NEXT_DATA__").inner_text()
            return json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("browser_next_data_failed", url=url, error=str(exc))
            return None
        finally:
            await page.close()