"""
core/poi_finder.py

Busca puntos de interés (supermercados, gimnasios, paradas de
colectivo, estaciones de tren) cerca de una coordenada usando la
Overpass API (OpenStreetMap) -- gratis y sin API key. Se usa para
validar los criterios de config/criterios.yaml (sección
"puntos_de_interes" y el chequeo de transporte público en "ubicacion").

También expone haversine_km(), una distancia en línea recta entre dos
coordenadas: se usa como proxy de "tiempo de viaje" a un punto de
referencia fijo (ver main.py) ya que no hay un servicio de rutas/tiempo
de viaje real conectado (requeriría una API paga, ej. Google Distance
Matrix).
"""

from __future__ import annotations

import logging
import math
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "scraper-alquiler/1.0 (uso personal, no comercial)"
MIN_SECONDS_BETWEEN_REQUESTS = 1.0
RADIO_TIERRA_KM = 6371.0

# Nombres "humanos" (los que se usan en criterios.yaml) -> tags OSM.
# Un tipo puede matchear más de un tag (ej. un supermercado chico a
# veces está tageado como shop=convenience en vez de shop=supermarket).
POI_TAGS = {
    "supermercado": ["shop=supermarket", "shop=convenience"],
    "gimnasio": ["leisure=fitness_centre", "sport=fitness"],
    "colectivo": ["highway=bus_stop"],
    "tren": ["railway=station", "railway=halt"],
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en línea recta entre dos coordenadas, en km."""
    rlat1, rlon1, rlat2, rlon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * RADIO_TIERRA_KM * math.asin(math.sqrt(a))


class POIFinder:
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self._cache: dict[tuple, bool] = {}
        self._ultima_request = 0.0

    def _throttle(self) -> None:
        transcurrido = time.monotonic() - self._ultima_request
        falta = MIN_SECONDS_BETWEEN_REQUESTS - transcurrido
        if falta > 0:
            time.sleep(falta)

    def _build_query(self, tipo: str, lat: float, lon: float, radio_metros: int) -> str:
        tags = POI_TAGS.get(tipo)
        if not tags:
            raise ValueError(f"Tipo de POI desconocido: '{tipo}'. Conocidos: {list(POI_TAGS)}")

        filtros = "".join(
            f'node["{clave}"="{valor}"](around:{radio_metros},{lat},{lon});'
            for tag in tags
            for clave, valor in [tag.split("=", 1)]
        )
        return f"[out:json][timeout:25];({filtros});out count;"

    def existe_cerca(self, tipo: str, lat: float, lon: float, radio_metros: int) -> bool:
        """True si hay al menos un POI del tipo dado dentro del radio."""
        clave_cache = (tipo, round(lat, 5), round(lon, 5), radio_metros)
        if clave_cache in self._cache:
            return self._cache[clave_cache]

        query = self._build_query(tipo, lat, lon, radio_metros)

        self._throttle()
        try:
            response = self.session.post(OVERPASS_URL, data={"data": query}, timeout=30)
            self._ultima_request = time.monotonic()
            response.raise_for_status()
            data = response.json()
        except Exception:
            logger.exception(
                "poi_finder: error consultando Overpass para '%s' en (%s, %s)", tipo, lat, lon
            )
            # Si Overpass falla (timeout, rate limit del servicio
            # público), preferimos no descartar la publicación por un
            # problema de red transitorio -- se cuela en el Sheet como
            # "no verificado" antes que perderla por una falla ajena.
            self._cache[clave_cache] = True
            return True

        elements = data.get("elements", [])
        total = 0
        if elements:
            primero = elements[0]
            if isinstance(primero, dict) and "tags" in primero and "total" in primero.get("tags", {}):
                total = int(primero["tags"]["total"])
            else:
                total = len(elements)

        existe = total > 0
        self._cache[clave_cache] = existe
        return existe
