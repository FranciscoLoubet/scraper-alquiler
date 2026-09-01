"""
utils/http.py

Sesión HTTP compartida para los scrapers: rotación de User-Agent y un
delay (+ jitter) entre requests, para no pegarle demasiado rápido a
los sitios de origen (algunos devuelven 403/429 si detectan scraping
agresivo).
"""

from __future__ import annotations

import logging
import random
import time

import requests

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]


class ThrottledSession(requests.Session):
    """
    Session de requests que espera `delay_seconds` (+ jitter) entre
    cada request saliente, para simular un ritmo más humano.
    """

    def __init__(self, delay_seconds: float = 1.5, jitter_seconds: float = 0.5):
        super().__init__()
        self.headers.setdefault("User-Agent", random.choice(USER_AGENTS))
        self.headers.setdefault("Accept-Language", "es-AR,es;q=0.9,en;q=0.8")
        self.delay_seconds = delay_seconds
        self.jitter_seconds = jitter_seconds
        self._ultima_request = 0.0

    def request(self, *args, **kwargs):
        transcurrido = time.monotonic() - self._ultima_request
        espera = self.delay_seconds + random.uniform(0, self.jitter_seconds) - transcurrido
        if espera > 0:
            time.sleep(espera)
        try:
            return super().request(*args, **kwargs)
        finally:
            self._ultima_request = time.monotonic()


def build_session(delay_seconds: float = 1.5) -> ThrottledSession:
    return ThrottledSession(delay_seconds=delay_seconds)
