"""
main.py

Orquestador principal: corre todos los scrapers configurados, normaliza
las publicaciones a Listing, aplica los criterios de negocio
(config/criterios.yaml) -- amueblado, capacidad (2 o 4 personas) +
precio máximo por persona, y puntos de interés obligatorios --,
clasifica las que sobreviven según qué tan cerca están de la
universidad (caminando, combi, tren, colectivo o nada), descarta
duplicados ya vistos en corridas anteriores, y escribe las
publicaciones nuevas -- ordenadas por esa clasificación -- a Google
Sheets.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

from core.currency import CotizacionDolar
from core.dedup import Deduplicator
from core.filters import FilterConfig, apply_filters
from core.geocoder import Geocoder
from core.models import Listing
from core.normalizer import normalize_many
from core.poi_finder import POIFinder, distancia_minima_km, haversine_km
from core.puntos_referencia import resolver_puntos
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

# Niveles de prioridad de ubicación/transporte, del mejor (0) al peor.
# Ver el comentario de la sección `transporte` en config/criterios.yaml.
NIVEL_CAMINANDO = 0
NIVEL_COMBI = 1
NIVEL_TREN_COSTA = 2
NIVEL_TREN_MITRE = 3
NIVEL_COLECTIVO = 4
NIVEL_SIN_TRANSPORTE = 5

ETIQUETAS_NIVEL = {
    NIVEL_CAMINANDO: "Caminando a la universidad",
    NIVEL_COMBI: "Combi universitaria",
    NIVEL_TREN_COSTA: "Tren de la Costa",
    NIVEL_TREN_MITRE: "Tren Mitre",
    NIVEL_COLECTIVO: "Colectivo",
    NIVEL_SIN_TRANSPORTE: "Sin transporte cercano",
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


def cumple_capacidad_y_precio(
    listing: Listing, criterios: dict, cotizador: CotizacionDolar
) -> bool:
    """
    Se queda solo con departamentos para 2 o 4 personas (según el
    mapeo ambientes -> personas de criterios.yaml) y con precio, ya
    convertido a ARS si hace falta, dentro del tope por persona.
    """
    capacidad_cfg = criterios.get("capacidad") or {}
    mapeo = capacidad_cfg.get("ambientes_a_personas") or {}
    if not mapeo:
        return True  # sin mapeo configurado, no filtramos por esto

    personas = mapeo.get(int(listing.ambientes)) if listing.ambientes else None
    if personas is None:
        return False  # ambientes fuera de las capacidades que interesan (2 o 4 personas)

    precio_persona_cfg = criterios.get("precio_por_persona") or {}
    tope_por_persona = precio_persona_cfg.get("maximo")
    if tope_por_persona is None:
        return True

    if listing.precio is None:
        return False  # no hay precio, no se puede evaluar contra el tope

    precio_ars = cotizador.a_ars(listing.precio, listing.moneda)
    if precio_ars is None:
        logger.warning(
            "No se pudo convertir a ARS el precio de '%s' (%s %s), la descarto por las dudas",
            listing.url,
            listing.precio,
            listing.moneda,
        )
        return False

    return precio_ars <= tope_por_persona * personas


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


def clasificar_ubicacion(
    listing: Listing,
    criterios: dict,
    referencia_uni: Optional[tuple[float, float]],
    puntos_combi: list[tuple[float, float]],
    puntos_tren_costa: list[tuple[float, float]],
    puntos_tren_mitre: list[tuple[float, float]],
    geocoder: Geocoder,
    poi_finder: POIFinder,
) -> tuple[int, str]:
    """
    Devuelve (nivel, etiqueta) según qué tan conveniente es llegar a
    la universidad desde esta publicación. No descarta nada -- ver el
    comentario de la sección `transporte` en config/criterios.yaml.
    """
    transporte_cfg = criterios.get("transporte") or {}

    lat, lon = listing.lat, listing.lon
    if lat is None or lon is None:
        geocodificado = geocoder.geocode(listing.ubicacion)
        if geocodificado is None:
            logger.info(
                "No se pudo geocodificar '%s', no puedo clasificar su ubicación",
                listing.ubicacion,
            )
            return (NIVEL_SIN_TRANSPORTE, ETIQUETAS_NIVEL[NIVEL_SIN_TRANSPORTE])
        lat, lon = geocodificado

    if referencia_uni is not None:
        radio_caminata = transporte_cfg.get("radio_caminata_uni_km", 1.5)
        if haversine_km(lat, lon, referencia_uni[0], referencia_uni[1]) <= radio_caminata:
            return (NIVEL_CAMINANDO, ETIQUETAS_NIVEL[NIVEL_CAMINANDO])

    combi_cfg = transporte_cfg.get("combis") or {}
    d_combi = distancia_minima_km(lat, lon, puntos_combi)
    if d_combi is not None and d_combi * 1000 <= combi_cfg.get("radio_metros", 600):
        return (NIVEL_COMBI, ETIQUETAS_NIVEL[NIVEL_COMBI])

    tren_costa_cfg = transporte_cfg.get("tren_costa") or {}
    d_tren_costa = distancia_minima_km(lat, lon, puntos_tren_costa)
    if d_tren_costa is not None and d_tren_costa * 1000 <= tren_costa_cfg.get("radio_metros", 700):
        return (NIVEL_TREN_COSTA, ETIQUETAS_NIVEL[NIVEL_TREN_COSTA])

    tren_mitre_cfg = transporte_cfg.get("tren_mitre") or {}
    d_tren_mitre = distancia_minima_km(lat, lon, puntos_tren_mitre)
    if d_tren_mitre is not None and d_tren_mitre * 1000 <= tren_mitre_cfg.get("radio_metros", 700):
        return (NIVEL_TREN_MITRE, ETIQUETAS_NIVEL[NIVEL_TREN_MITRE])

    colectivo_cfg = transporte_cfg.get("colectivo") or {}
    radio_colectivo = colectivo_cfg.get("radio_metros", 400)
    if poi_finder.existe_cerca("colectivo", lat, lon, radio_colectivo):
        return (NIVEL_COLECTIVO, ETIQUETAS_NIVEL[NIVEL_COLECTIVO])

    return (NIVEL_SIN_TRANSPORTE, ETIQUETAS_NIVEL[NIVEL_SIN_TRANSPORTE])


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

    cotizador = CotizacionDolar()
    con_capacidad_precio = [
        l for l in filtradas if cumple_capacidad_y_precio(l, criterios, cotizador)
    ]
    logger.info(
        "%d publicaciones cumplen capacidad (2 o 4 personas) y precio por persona",
        len(con_capacidad_precio),
    )

    geocoder = Geocoder(cache_path=GEOCODE_CACHE_PATH)
    poi_finder = POIFinder(cache_path=POI_CACHE_PATH)

    con_poi = [
        l for l in con_capacidad_precio if cumple_puntos_de_interes(l, criterios, geocoder, poi_finder)
    ]
    logger.info("%d publicaciones cumplen los puntos de interés requeridos", len(con_poi))

    referencia_uni = resolver_punto_referencia(criterios, geocoder)

    # resolver_puntos() usa el mismo geocoder de arriba, así que las
    # direcciones de combis/estaciones quedan cacheadas en el mismo
    # GEOCODE_CACHE_PATH que las ubicaciones de las publicaciones --
    # no hace falta un cache aparte para estos puntos fijos.
    transporte_cfg = criterios.get("transporte") or {}
    puntos_combi = resolver_puntos((transporte_cfg.get("combis") or {}).get("puntos") or [], geocoder)
    puntos_tren_costa = resolver_puntos(
        (transporte_cfg.get("tren_costa") or {}).get("puntos") or [], geocoder
    )
    puntos_tren_mitre = resolver_puntos(
        (transporte_cfg.get("tren_mitre") or {}).get("puntos") or [], geocoder
    )

    for listing in con_poi:
        nivel, etiqueta = clasificar_ubicacion(
            listing,
            criterios,
            referencia_uni,
            puntos_combi,
            puntos_tren_costa,
            puntos_tren_mitre,
            geocoder,
            poi_finder,
        )
        listing.prioridad_ubicacion = nivel
        listing.medio_transporte = etiqueta

    # Orden: mejor ubicación primero (caminando > combi > tren costa >
    # tren mitre > colectivo > nada) y, dentro de un mismo nivel, el
    # precio más bajo primero. Esto solo ordena las publicaciones
    # nuevas de esta corrida -- el Sheet es append-only, así que no
    # reordena filas ya escritas en corridas anteriores.
    con_poi.sort(key=lambda l: (l.prioridad_ubicacion, l.precio if l.precio is not None else float("inf")))

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
