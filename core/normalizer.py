"""
core/normalizer.py

Convierte el dict crudo que devuelve Scraper.run() (ver sites/base.py)
al modelo Listing (core/models.py). El contrato original de
sites/base.py pide un campo "capacidad"; Listing lo llama "ambientes"
-- acá centralizamos ese (y futuros) mapeos en un solo lugar, en vez
de tocar cada scraper o duplicar el traductor en main.py.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from core.models import Listing

logger = logging.getLogger(__name__)

# alias de campo -> nombre canónico esperado por Listing.
FIELD_ALIASES = {
    "capacidad": "ambientes",
}


def _apply_aliases(raw: dict) -> dict:
    data = dict(raw)
    for alias, canonical in FIELD_ALIASES.items():
        if alias in data and canonical not in data:
            data[canonical] = data.pop(alias)
    return data


def normalize_one(raw: dict, sitio_origen: Optional[str] = None) -> Optional[Listing]:
    """
    Convierte un dict crudo a Listing. Devuelve None (en vez de
    propagar la excepción) si falta algo obligatorio -- así una
    publicación mal formada no tira abajo el resto del batch.
    """
    if not isinstance(raw, dict):
        logger.warning("normalizer: raw no es un dict, lo descarto: %r", raw)
        return None

    data = _apply_aliases(raw)
    if sitio_origen and not data.get("sitio_origen"):
        data["sitio_origen"] = sitio_origen

    try:
        return Listing.from_dict(data)
    except (ValueError, TypeError) as e:
        # ValueError: Listing.__post_init__ rechaza url/sitio_origen
        # vacíos. TypeError: Listing.from_dict no rellena los
        # obligatorios que falten directamente como key en el dict
        # (ej. raw sin "url"), así que el dataclass explota al
        # construirse en vez de validar -- lo tratamos igual acá.
        logger.warning("normalizer: publicación descartada (%s): %s", e, data.get("url"))
        return None


def normalize_many(raws: Iterable[dict], sitio_origen: Optional[str] = None) -> list[Listing]:
    listings: list[Listing] = []
    for raw in raws:
        listing = normalize_one(raw, sitio_origen=sitio_origen)
        if listing is not None:
            listings.append(listing)
    return listings
