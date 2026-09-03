"""
core/puntos_referencia.py

Resuelve una lista de "puntos fijos" (nombre + dirección, ej. las
paradas de combi o las estaciones de tren definidas en
config/criterios.yaml) a coordenadas lat/lon.

Prioridad para cada punto:
1. lat/lon cargados a mano en el YAML -- siempre gana, no se
   geocodifica.
2. Geocoding vía Nominatim (core/geocoder.py). El propio Geocoder ya
   cachea a disco (ver `cache_path` en su constructor y
   core/disk_cache.py), así que estos puntos fijos quedan cacheados
   junto con las ubicaciones normales de las publicaciones -- no hace
   falta un cache aparte acá.

Si un punto no se puede geocodificar (dirección imprecisa, Nominatim
caído), se lo ignora con un warning en vez de romper el pipeline --
el llamador simplemente tiene un punto de referencia menos para ese
tipo de transporte.
"""

from __future__ import annotations

import logging

from core.geocoder import Geocoder

logger = logging.getLogger(__name__)

Coordenadas = tuple[float, float]


def resolver_puntos(puntos: list[dict], geocoder: Geocoder) -> list[Coordenadas]:
    """Resuelve una lista de puntos (dicts con nombre/direccion/lat/lon) a coordenadas.

    Los puntos que no se pudieron resolver se omiten del resultado en
    vez de cortar el resto.
    """
    resueltos: list[Coordenadas] = []
    for punto in puntos:
        lat, lon = punto.get("lat"), punto.get("lon")
        if lat is not None and lon is not None:
            resueltos.append((float(lat), float(lon)))
            continue

        direccion = punto.get("direccion")
        if not direccion:
            continue

        coords = geocoder.geocode(direccion)
        if coords is None:
            logger.warning(
                "No se pudo geocodificar '%s' (%s) -- cargá lat/lon a mano en "
                "config/criterios.yaml para este punto si esto sigue fallando",
                punto.get("nombre", direccion),
                direccion,
            )
            continue

        resueltos.append(coords)

    return resueltos
