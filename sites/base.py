from abc import ABC, abstractmethod
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class Scraper(ABC):
    """Contrato que debe cumplir todo scraper de un sitio."""

    nombre_sitio: str  # ej: "zonaprop"

    def __init__(self, session="None"):
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

    def run(self) -> list[dict]:
        """Punto de entrada único: trae el listado y parsea cada item,
        sin que un error en una publicación tire abajo todo el resto.
        """
        publicaciones = []
        for raw in self.fetch_listings():
            try:
                publicaciones.append(self.parse_listing(raw))
            except Exception as e:
                logger.warning(f"[{self.nombre_sitio}] error parseando publicación: {e}")
        return publicaciones