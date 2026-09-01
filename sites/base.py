from abc import ABC, abstractmethod
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class Scraper(ABC):
    """Contrato que debe cumplir todo scraper de un sitio."""

    nombre_sitio: str = "desconocido"  # ej: "zonaprop"

    def __init__(self, session=None):
        # más adelante esto va a recibir la sesión de utils/http.py
        # (rotación de user-agent, delays) en vez de crear una propia acá
        self.session = session

    @abstractmethod
    def fetch_listings(self) -> list[dict]:
        """Devuelve una lista de publicaciones crudas (dicts) encontradas en la búsqueda."""
        ...

    @abstractmethod
    def parse_listing(self, raw: dict) -> dict:
        """Toma UNA publicación cruda y devuelve un dict normalizado con,
        como mínimo: precio, moneda, capacidad, amueblado, ubicacion,
        url, lat, lon, fecha_scrapeo, sitio_origen.
        """
        ...

    def _timestamp(self) -> str:
        return datetime.now().isoformat()

    def _site_name(self) -> str:
        return getattr(self, "nombre_sitio", None) or "desconocido"

    def _publication_id(self, raw: dict | None) -> str:
        if not isinstance(raw, dict):
            return "<raw no dict>"

        for key in ("url", "link", "id", "slug", "titulo", "ubicacion"):
            value = raw.get(key)
            if value not in (None, ""):
                return str(value)

        return str(raw)

    def run(self) -> list[dict]:
        """Punto de entrada único: trae el listado y parsea cada item,
        sin que un error en una publicación tire abajo todo el resto.
        """
        publicaciones = []
        try:
            raws = self.fetch_listings()
        except Exception:
            logger.exception("[%s] error fetching listings", self._site_name())
            return []

        for raw in raws or []:
            try:
                publicaciones.append(self.parse_listing(raw))
            except Exception:
                logger.exception(
                    "[%s] error parseando publicación: %s",
                    self._site_name(),
                    self._publication_id(raw),
                )
        return publicaciones
