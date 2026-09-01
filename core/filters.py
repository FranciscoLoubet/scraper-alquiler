"""
Filtros de negocio sobre publicaciones ya normalizadas (Listing).
Pensado para configurarse una vez (ej. desde un YAML/env/CLI args) y
aplicarse sobre cualquier lista de Listing, sin importar de qué sitio
vinieron -- así el filtro es el mismo sin importar si agregás
Argenprop, Mercado Libre, etc. más adelante.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Iterable, Optional

from core.models import Listing

logger = logging.getLogger(__name__)


@dataclass
class FilterConfig:
    precio_min: Optional[float] = 100000
    precio_max: Optional[float] = None
    moneda: Optional[str] = None  # ej "ARS" o "USD"; None = no filtra por moneda

    ambientes_min: Optional[float] = None
    ambientes_max: Optional[float] = None

    expensas_max: Optional[float] = None

    amueblado: Optional[bool] = None  # None = no filtra; True/False = exige ese valor exacto

    # match parcial e insensible a mayúsculas: "palermo" matchea
    # "Palermo, CABA". Vacío = no filtra por ubicación.
    ubicaciones_permitidas: set[str] = field(default_factory=set)

    requerir_geolocalizacion: bool = False  # exige lat y lon no nulos


def _cumple(listing: Listing, config: FilterConfig) -> bool:
    # listing.precio puede ser None si el scraper no lo pudo extraer
    # (ver core/models.py). Ese caso se filtra ANTES de llegar acá, en
    # apply_filters(), para poder loguearlo con un motivo distinto al
    # de "no llega al precio mínimo". Acá adentro, si hay un filtro de
    # precio activo, listing.precio ya está garantizado no-None.
    if config.precio_min is not None and listing.precio < config.precio_min:
        return False
    if config.precio_max is not None and listing.precio > config.precio_max:
        return False

    # ambientes sigue defaulteando a 0.0 (no a None) en core/models.py,
    # así que ambientes_min todavía puede confundir "sin dato" con
    # "0 ambientes". Si te pasa lo mismo que con precio, avisame y
    # replico el mismo tratamiento acá.
    if config.moneda is not None and listing.moneda.upper() != config.moneda.upper():
        return False

    if config.ambientes_min is not None and listing.ambientes < config.ambientes_min:
        return False
    if config.ambientes_max is not None and listing.ambientes > config.ambientes_max:
        return False

    if config.expensas_max is not None and listing.expensas > config.expensas_max:
        return False

    if config.amueblado is not None and listing.amueblado != config.amueblado:
        return False

    if config.ubicaciones_permitidas:
        ubicacion_normalizada = listing.ubicacion.strip().lower()
        permitidas_normalizadas = {u.strip().lower() for u in config.ubicaciones_permitidas}
        if not any(permitida in ubicacion_normalizada for permitida in permitidas_normalizadas):
            return False

    if config.requerir_geolocalizacion and (listing.lat is None or listing.lon is None):
        return False

    return True


def apply_filters(listings: Iterable[Listing], config: FilterConfig) -> list[Listing]:
    listings = list(listings)
    hay_filtro_de_precio = config.precio_min is not None or config.precio_max is not None

    filtradas: list[Listing] = []
    sin_precio = 0

    for listing in listings:
        if hay_filtro_de_precio and listing.precio is None:
            # No lo descartamos por "precio bajo": lo descartamos
            # porque no hay dato para comparar. Se cuenta aparte para
            # no mezclar ambos motivos en el mismo número.
            sin_precio += 1
            continue
        if _cumple(listing, config):
            filtradas.append(listing)

    if sin_precio:
        logger.info(
            f"Filtros: {sin_precio} publicaciones excluidas por no tener precio "
            f"extraído (no se pudo comparar contra precio_min/precio_max)"
        )
    logger.info(f"Filtros: {len(filtradas)} de {len(listings)} publicaciones pasaron")
    return filtradas