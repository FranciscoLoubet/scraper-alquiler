"""
Modelo de datos central del proyecto. Los scrapers (ver base.py /
zonaprop.py) devuelven dicts normalizados desde parse_listing(); acá
los convertimos a un objeto Listing con validación básica, para que
todo lo que venga después (dedup, filters, sheets_writer) trabaje
contra un tipo conocido en vez de contra dicts sueltos con keys que
podrían faltar o tener el tipo equivocado.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, asdict, field
from datetime import datetime, timezone
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class Listing:
    # Obligatorios: sin url no hay dedup posible, sin sitio_origen no
    # sabés de dónde salió el dato.
    url: str
    sitio_origen: str

    # Con default: si el scraper no pudo extraerlos, preferimos un
    # valor "neutro" y logueado antes que romper todo el pipeline.
    precio: Optional[float] = None  # None = no se pudo extraer, distinto de "vale 0"
    moneda: str = "ARS"
    expensas: float = 0.0
    ambientes: float = 0.0
    amueblado: Optional[bool] = None  # None = "sin dato", no asumas False
    ubicacion: str = "Desconocido"
    lat: Optional[float] = None
    lon: Optional[float] = None
    fecha_scrapeo: str = field(default="")

    # Calculados en main.py después de filtrar (no vienen del scraper):
    # qué tan conveniente es el transporte hacia la universidad. None
    # hasta que main.py los completa vía clasificar_ubicacion().
    prioridad_ubicacion: Optional[int] = None  # 0 = mejor (caminando), más alto = peor
    medio_transporte: Optional[str] = None  # ej. "Combi universitaria", "Tren de la Costa"

    # Orden de columnas para exportar (Sheets, CSV, etc.). Cambiarlo acá
    # cambia el orden en todos lados que usen to_row().
    HEADERS = [
        "url",
        "sitio_origen",
        "precio",
        "moneda",
        "expensas",
        "ambientes",
        "amueblado",
        "ubicacion",
        "lat",
        "lon",
        "fecha_scrapeo",
        "prioridad_ubicacion",
        "medio_transporte",
    ]

    def __post_init__(self):
        if not self.fecha_scrapeo:
            self.fecha_scrapeo = datetime.now(timezone.utc).isoformat()

        if not self.url:
            raise ValueError("Listing requiere 'url' no vacía")
        if not self.sitio_origen:
            raise ValueError("Listing requiere 'sitio_origen' no vacío")

        # Coerción defensiva: un scraper puede devolver "" o None en
        # campos numéricos cuando el sitio no expone el dato. Preferimos
        # normalizar acá en un solo lugar antes que repetir este chequeo
        # en cada consumidor (dedup, filters, sheets_writer...).
        self.precio = self._to_float_or_none(self.precio, "precio")
        self.expensas = self._to_float(self.expensas, 0.0, "expensas")
        self.ambientes = self._to_float(self.ambientes, 0.0, "ambientes")
        self.lat = self._to_float_or_none(self.lat, "lat")
        self.lon = self._to_float_or_none(self.lon, "lon")
        self.moneda = (self.moneda or "ARS").strip().upper()
        self.ubicacion = (self.ubicacion or "Desconocido").strip()

    def _to_float(self, value: Any, default: float, campo: str) -> float:
        if value is None or value == "":
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            logger.warning(
                f"[{self.sitio_origen}] valor inválido para '{campo}': {value!r}, uso default {default}"
            )
            return default

    def _to_float_or_none(self, value: Any, campo: str) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            logger.warning(f"[{self.sitio_origen}] valor inválido para '{campo}': {value!r}, uso None")
            return None

    @classmethod
    def from_dict(cls, data: dict) -> "Listing":
        """
        Construye un Listing a partir del dict que devuelve
        Scraper.parse_listing(). Ignora keys extra que no formen parte
        del contrato, en vez de fallar por un campo de más.
        """
        campos_validos = {f.name for f in fields(cls)}
        filtrado = {k: v for k, v in data.items() if k in campos_validos}
        return cls(**filtrado)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_row(self) -> list[Any]:
        """Fila en el mismo orden que HEADERS, lista para exportar."""
        d = self.to_dict()
        return [d[campo] for campo in self.HEADERS]

    @property
    def dedup_key(self) -> str:
        """
        Clave de deduplicación. Por ahora, URL normalizada (sin barra
        final, en minúsculas). Si algún sitio agrega query params
        random a la misma publicación entre corridas, esto se va a
        romper y va a haber que sumar una normalización más agresiva
        (ej. sacar query string) o usar un id propio del sitio.
        """
        return self.url.strip().rstrip("/").lower()