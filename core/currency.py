"""
core/currency.py

Cotización ARS/USD para poder comparar precios publicados en distinta
moneda contra un mismo tope (ej. precio máximo por persona). Usa la
API pública y gratuita de dolarapi.com (cotización "blue", la de
referencia informal más usada en Argentina) -- sin API key.

Si la consulta falla (red, servicio caído), a_ars() devuelve None y
quien llama decide qué hacer -- ver main.py, que prefiere descartar
esa publicación puntual antes que dejarla pasar sin poder verificar
el precio.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

DOLAR_BLUE_URL = "https://dolarapi.com/v1/dolares/blue"
CACHE_SECONDS = 3600  # la cotización no cambia tan seguido como para pedirla en cada publicación


class CotizacionDolar:
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self._venta: Optional[float] = None
        self._ultima_consulta = 0.0

    def ars_por_usd(self) -> Optional[float]:
        """Cuántos ARS vale 1 USD (cotización de venta). None si no se pudo obtener nunca."""
        ahora = time.monotonic()
        if self._venta is not None and (ahora - self._ultima_consulta) < CACHE_SECONDS:
            return self._venta

        try:
            response = self.session.get(DOLAR_BLUE_URL, timeout=10)
            response.raise_for_status()
            data = response.json()
            self._venta = float(data["venta"])
            self._ultima_consulta = ahora
        except Exception:
            logger.exception("currency: no se pudo obtener la cotización del dólar")
            return self._venta  # lo último que tengamos cacheado, aunque esté vencido (puede ser None)

        return self._venta

    def a_ars(self, monto: float, moneda: str) -> Optional[float]:
        """Convierte `monto` de `moneda` a ARS. None si hace falta la cotización y no se pudo obtener."""
        moneda = (moneda or "ARS").strip().upper()
        if moneda == "ARS":
            return monto
        if moneda == "USD":
            tasa = self.ars_por_usd()
            if tasa is None:
                return None
            return monto * tasa
        logger.warning("currency: moneda desconocida '%s', no puedo convertir a ARS", moneda)
        return None
