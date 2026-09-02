"""
utils/browser.py

Sesión de scraping respaldada por un navegador Chromium real
(Playwright), para sitios como ZonaProp que están detrás de Cloudflare
y exigen resolver un challenge en JavaScript antes de servir el HTML
-- algo que `requests`, por más headers "de navegador" que se le
agreguen, no puede hacer porque nunca ejecuta JS.

Expone una interfaz mínima compatible con requests.Session (`.get()`
devolviendo un objeto con `.text` / `.status_code` / `.raise_for_status()`,
y un dict `.headers`) para que los scrapers existentes no tengan que
saber si están hablando con `requests` o con un navegador real.
"""

from __future__ import annotations

import logging
import random
import time

import requests
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

# Cloudflare (y otros WAF) marcan al Chromium de Playwright como bot
# principalmente por `navigator.webdriver`. Este flag se lo saca de encima;
# no es infalible, pero junto con headless=False resuelve la gran mayoría
# de los challenges "Just a moment...".
_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]


class BrowserResponse:
    """Respuesta liviana, compatible con la porción de la API de
    `requests.Response` que usan los scrapers (`.text`, `.status_code`,
    `.raise_for_status()`)."""

    def __init__(self, text: str, status_code: int, url: str):
        self.text = text
        self.status_code = status_code
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code and self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f"{self.status_code} Client Error for url: {self.url}"
            )


class BrowserSession:
    """
    Sesión de scraping que usa un navegador Chromium real vía
    Playwright en lugar de `requests`, para poder pasar el challenge JS
    de Cloudflare. Mantiene un único browser/context vivo entre
    requests para conservar la cookie `cf_clearance` (y otras) una vez
    resuelto el challenge, en vez de tener que resolverlo de nuevo en
    cada página.
    """

    def __init__(
        self,
        delay_seconds: float = 2.0,
        jitter_seconds: float = 1.0,
        headless: bool = True,
        challenge_wait_seconds: float = 20.0,
    ):
        self.headers: dict[str, str] = {}
        self.delay_seconds = delay_seconds
        self.jitter_seconds = jitter_seconds
        self.challenge_wait_seconds = challenge_wait_seconds
        self._ultima_request = 0.0
        self._headers_aplicados = False

        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(
                headless=headless, args=_LAUNCH_ARGS
            )
            self._context = self._browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                locale="es-AR",
                viewport={"width": 1366, "height": 768},
            )
            self._page = self._context.new_page()
        except Exception:
            self._playwright.stop()
            raise

    def _throttle(self) -> None:
        transcurrido = time.monotonic() - self._ultima_request
        espera = self.delay_seconds + random.uniform(0, self.jitter_seconds) - transcurrido
        if espera > 0:
            time.sleep(espera)

    def _esperar_challenge_cloudflare(self) -> None:
        deadline = time.monotonic() + self.challenge_wait_seconds
        while time.monotonic() < deadline:
            try:
                title = self._page.title()
            except Exception:
                return
            if "just a moment" not in title.lower():
                return
            time.sleep(1)
        logger.warning("Timeout esperando a que se resuelva el challenge de Cloudflare")

    def get(self, url: str, timeout: int = 20) -> BrowserResponse:
        if not self._headers_aplicados and self.headers:
            self._context.set_extra_http_headers(self.headers)
            self._headers_aplicados = True

        self._throttle()
        try:
            response = self._page.goto(
                url, timeout=timeout * 1000, wait_until="domcontentloaded"
            )
            self._esperar_challenge_cloudflare()
            text = self._page.content()
            status_code = response.status if response else 200
        finally:
            self._ultima_request = time.monotonic()

        return BrowserResponse(text=text, status_code=status_code, url=url)

    def close(self) -> None:
        try:
            self._context.close()
            self._browser.close()
        except Exception:
            logger.exception("Error cerrando el navegador de scraping")
        finally:
            self._playwright.stop()

    def __enter__(self) -> "BrowserSession":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def build_browser_session(delay_seconds: float = 2.0, headless: bool = True) -> BrowserSession:
    return BrowserSession(delay_seconds=delay_seconds, headless=headless)
