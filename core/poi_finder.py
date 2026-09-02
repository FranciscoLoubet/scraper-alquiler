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
from pathlib import Path
from typing import Optional

import requests

from core.disk_cache import DiskCache

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


MAX_FALLOS_CONSECUTIVOS = 3


class POIFinder:
    def __init__(
        self,
        session: Optional[requests.Session] = None,
        cache_path: str | Path | None = None,
    ):
        self.session = session or requests.Session()
        # requests.Session() ya trae un User-Agent propio
        # ("python-requests/x.y.z") seteado en session.headers por
        # default, así que .setdefault() nunca lo pisa. Overpass
        # rechaza ese User-Agent genérico con 406 -- hace falta
        # asignarlo directo para que efectivamente viaje el nuestro.
        self.session.headers["User-Agent"] = USER_AGENT
        # cache_path=None (default) deja el cache solo en memoria, para
        # no ensuciar de I/O los tests o corridas puntuales. main.py le
        # pasa un archivo real para no re-consultar Overpass entre
        # corridas para la misma coordenada.
        self._cache = DiskCache(cache_path)
        # A diferencia del cache persistente, esto vive solo en
        # memoria: un fallo transitorio (timeout, rate limit) no debe
        # "recordarse para siempre" como si ahí no hubiera POIs, pero
        # sí evitamos reintentar la misma consulta fallida dentro de
        # esta misma corrida.
        self._fallos_este_proceso: set[str] = set()
        self._ultima_request = 0.0
        self._fallos_consecutivos = 0
        self._circuito_abierto = False

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
        clave_cache = f"{tipo}:{round(lat, 5)}:{round(lon, 5)}:{radio_metros}"
        if clave_cache in self._cache:
            return self._cache.get(clave_cache)
        if clave_cache in self._fallos_este_proceso:
            return True

        if self._circuito_abierto:
            # Ya vimos suficientes fallos seguidos como para asumir que
            # Overpass está caído/inalcanzable en esta corrida. Frenamos
            # de golpe en vez de seguir esperando el timeout (30s) en
            # cada publicación -- si insistiéramos, con decenas de
            # publicaciones el script puede tardar más de una hora en
            # terminar solo reintentando un servicio que no va a responder.
            return True

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
            # No lo persistimos en el cache en disco: un fallo transitorio
            # no debe convertirse en un "sí hay POI" permanente.
            self._fallos_este_proceso.add(clave_cache)
            self._fallos_consecutivos += 1
            if self._fallos_consecutivos >= MAX_FALLOS_CONSECUTIVOS:
                self._circuito_abierto = True
                logger.warning(
                    "poi_finder: %d fallos seguidos contra Overpass, dejo de consultarlo "
                    "por el resto de la corrida",
                    self._fallos_consecutivos,
                )
            return True

        self._fallos_consecutivos = 0
        elements = data.get("elements", [])
        total = 0
        if elements:
            primero = elements[0]
            if isinstance(primero, dict) and "tags" in primero and "total" in primero.get("tags", {}):
                total = int(primero["tags"]["total"])
            else:
                total = len(elements)

        existe = total > 0
        self._cache.set(clave_cache, existe)
        self._cache.persist()
        return existe
