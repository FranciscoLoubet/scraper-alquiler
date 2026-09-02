"""
main.py

Orquestador principal: corre todos los scrapers configurados, normaliza
las publicaciones a Listing, aplica los criterios de negocio
(config/criterios.yaml) -- precio/ambientes/amueblado, distancia a la
universidad + transporte público, y puntos de interés obligatorios --,
descarta duplicados ya vistos en corridas anteriores, y escribe las
publicaciones nuevas que pasan todos los filtros a Google Sheets.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

from core.dedup import Deduplicator
from core.filters import FilterConfig, apply_filters
from core.geocoder import Geocoder
from core.models import Listing
from core.normalizer import normalize_many
from core.poi_finder import POIFinder, haversine_km
from notifiers.sheets_writer import SheetsWriter
from sites.zonaprop import ZonapropScraper
from utils.browser import build_browser_session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
CRITERIOS_PATH = BASE_DIR / "config" / "criterios.yaml"
DEDUP_STORAGE_PATH = BASE_DIR / "data" / "vistos.json"
GEOCODE_CACHE_PATH = BASE_DIR / "data" / "geocode_cache.json"
POI_CACHE_PATH = BASE_DIR / "data" / "poi_cache.json"

# URLs de búsqueda por sitio. Quedan acá (no en criterios.yaml) porque
# son parámetros de scraping, no criterios de negocio sobre el
# Listing ya normalizado.
SEARCH_URLS = {
    "zonaprop": "https://www.zonaprop.com.ar/departamentos-alquiler-vicente-lopez-san-isidro.html",
}


def cargar_criterios() -> dict:
    if not CRITERIOS_PATH.exists():
        logger.warning("No se encontró %s, sigo sin criterios de filtro", CRITERIOS_PATH)
        return {}
    with open(CRITERIOS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def construir_filter_config(criterios: dict) -> FilterConfig:
    precio = criterios.get("precio") or {}
    ambientes = criterios.get("ambientes") or {}
    amueblado_cfg = criterios.get("amueblado") or {}

    return FilterConfig(
        precio_min=precio.get("minimo"),
        precio_max=precio.get("maximo"),
        moneda=precio.get("moneda"),
        ambientes_min=ambientes.get("minimo"),
        ambientes_max=ambientes.get("maximo"),
        amueblado=amueblado_cfg.get("requerido"),
    )


def resolver_punto_referencia(
    criterios: dict, geocoder: Geocoder
) -> Optional[tuple[float, float]]:
    """
    Devuelve las coordenadas del punto de referencia (ej. la
    universidad). Si están hardcodeadas en criterios.yaml (lat/lon),
    las usa directo sin llamar a Nominatim -- es un punto fijo, no
    tiene sentido geocodificarlo en cada corrida, y así el pipeline no
    depende de que Nominatim esté disponible para esto. Si no están
    cargadas, geocodifica la dirección como fallback.
    """
    punto_ref_cfg = (criterios.get("ubicacion") or {}).get("punto_referencia") or {}
    lat, lon = punto_ref_cfg.get("lat"), punto_ref_cfg.get("lon")
    if lat is not None and lon is not None:
        return (float(lat), float(lon))

    direccion = punto_ref_cfg.get("direccion")
    if not direccion:
        return None

    referencia = geocoder.geocode(direccion)
    if referencia is None:
        logger.warning("No se pudo geocodificar el punto de referencia '%s'", direccion)
    return referencia


def cumple_puntos_de_interes(
    listing: Listing, criterios: dict, geocoder: Geocoder, poi_finder: POIFinder
) -> bool:
    poi_config = criterios.get("puntos_de_interes") or {}
    if not poi_config:
        return True

    lat, lon = listing.lat, listing.lon
    if lat is None or lon is None:
        geocodificado = geocoder.geocode(listing.ubicacion)
        if geocodificado is None:
            # Sin coordenadas no podemos chequear POIs. No descartamos
            # la publicación por esto -- solo lo logueamos, para no
            # perder publicaciones válidas por falta de geocoding.
            logger.info(
                "No se pudo geocodificar '%s', omito chequeo de POIs", listing.ubicacion
            )
            return True
        lat, lon = geocodificado

    for tipo, config_poi in poi_config.items():
        if not config_poi.get("requerido"):
            continue
        radio = config_poi.get("radio_metros", 500)
        if not poi_finder.existe_cerca(tipo, lat, lon, radio):
            return False

    return True


def cumple_ubicacion(
    listing: Listing,
    criterios: dict,
    referencia: Optional[tuple[float, float]],
    geocoder: Geocoder,
    poi_finder: POIFinder,
) -> bool:
    ubicacion_cfg = criterios.get("ubicacion") or {}
    if referencia is None:
        return True  # sin punto de referencia geocodificado, no filtramos por esto

    lat, lon = listing.lat, listing.lon
    if lat is None or lon is None:
        geocodificado = geocoder.geocode(listing.ubicacion)
        if geocodificado is None:
            logger.info(
                "No se pudo geocodificar '%s', no puedo evaluar distancia a la universidad",
                listing.ubicacion,
            )
            return True
        lat, lon = geocodificado

    distancia_km = haversine_km(lat, lon, referencia[0], referencia[1])
    distancia_maxima = ubicacion_cfg.get("distancia_maxima_km")
    if distancia_maxima is None or distancia_km <= distancia_maxima:
        return True

    transporte_cfg = ubicacion_cfg.get("transporte_publico_si_lejos") or {}
    if not transporte_cfg.get("requerido"):
        return False

    radio = transporte_cfg.get("radio_metros", 500)
    tiene_colectivo = poi_finder.existe_cerca("colectivo", lat, lon, radio)
    tiene_tren = poi_finder.existe_cerca("tren", lat, lon, radio)
    return tiene_colectivo or tiene_tren


def main() -> None:
    load_dotenv()
    criterios = cargar_criterios()
    filter_config = construir_filter_config(criterios)

    crudos = []
    with build_browser_session() as session:
        scrapers = [
            ZonapropScraper(session=session, initial_url=SEARCH_URLS["zonaprop"]),
        ]
        for scraper in scrapers:
            crudos.extend(scraper.run())
    logger.info("Scrapeadas %d publicaciones crudas", len(crudos))

    listings = normalize_many(crudos)
    logger.info("Normalizadas %d publicaciones", len(listings))

    filtradas = apply_filters(listings, filter_config)

    geocoder = Geocoder(cache_path=GEOCODE_CACHE_PATH)
    poi_finder = POIFinder(cache_path=POI_CACHE_PATH)

    referencia = resolver_punto_referencia(criterios, geocoder)

    con_ubicacion = [
        l for l in filtradas if cumple_ubicacion(l, criterios, referencia, geocoder, poi_finder)
    ]
    logger.info("%d publicaciones cumplen el criterio de ubicación/transporte", len(con_ubicacion))

    con_poi = [
        l for l in con_ubicacion if cumple_puntos_de_interes(l, criterios, geocoder, poi_finder)
    ]
    logger.info("%d publicaciones cumplen los puntos de interés requeridos", len(con_poi))

    dedup = Deduplicator(storage_path=DEDUP_STORAGE_PATH)
    nuevas = dedup.filter_new(con_poi)

    if not nuevas:
        logger.info("No hay publicaciones nuevas para notificar")
        return

    spreadsheet_id = os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID")
    credentials_path = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_PATH")
    if not spreadsheet_id or not credentials_path:
        logger.warning(
            "Faltan GOOGLE_SHEETS_SPREADSHEET_ID / GOOGLE_SHEETS_CREDENTIALS_PATH, "
            "no escribo a Sheets (revisá .env.example)"
        )
        return

    writer = SheetsWriter(credentials_path=credentials_path, spreadsheet_id=spreadsheet_id)
    writer.write(nuevas)


if __name__ == "__main__":
    main()
