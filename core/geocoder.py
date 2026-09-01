"""
core/geocoder.py

Geocodifica texto de ubicación ("Palermo, CABA") a lat/lon usando
Nominatim (OpenStreetMap), para publicaciones que no traen
coordenadas propias y para resolver puntos de referencia fijos (ej.
la universidad en config/criterios.yaml). Necesario para que
core/poi_finder.py pueda calcular distancias y buscar POIs cercanos.

Nominatim es gratis pero exige:
- User-Agent identificable (no el default de requests/urllib).
- Máximo 1 request/segundo.
Por eso hay throttle propio y un cache en memoria por corrida: no
tiene sentido volver a geocodificar la misma dirección varias veces
en el mismo proceso.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "scraper-alquiler/1.0 (uso personal, no comercial)"
MIN_SECONDS_BETWEEN_REQUESTS = 1.0

Coordenadas = tuple[float, float]


class Geocoder:
    def __init__(self, session: Optional[requests.Session] = None, country_bias: str = "ar"):
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.country_bias = country_bias
        self._cache: dict[str, Optional[Coordenadas]] = {}
        self._ultima_request = 0.0

    def _throttle(self) -> None:
        transcurrido = time.monotonic() - self._ultima_request
        falta = MIN_SECONDS_BETWEEN_REQUESTS - transcurrido
        if falta > 0:
            time.sleep(falta)

    def geocode(self, direccion: str) -> Optional[Coordenadas]:
        """Devuelve (lat, lon) o None si no se pudo geocodificar."""
        if not direccion or not direccion.strip():
            return None

        clave = direccion.strip().lower()
        if clave in self._cache:
            return self._cache[clave]

        self._throttle()
        try:
            response = self.session.get(
                NOMINATIM_URL,
                params={
                    "q": direccion,
                    "format": "json",
                    "limit": 1,
                    "countrycodes": self.country_bias,
                },
                timeout=10,
            )
            self._ultima_request = time.monotonic()
            response.raise_for_status()
            resultados = response.json()
        except Exception:
            logger.exception("geocoder: error geocodificando '%s'", direccion)
            self._cache[clave] = None
            return None

        if not resultados:
            logger.info("geocoder: sin resultados para '%s'", direccion)
            self._cache[clave] = None
            return None

        try:
            coords = (float(resultados[0]["lat"]), float(resultados[0]["lon"]))
        except (KeyError, TypeError, ValueError, IndexError):
            logger.warning("geocoder: respuesta inesperada para '%s': %r", direccion, resultados)
            self._cache[clave] = None
            return None

        self._cache[clave] = coords
        return coords
