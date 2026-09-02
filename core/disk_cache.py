"""
core/disk_cache.py

Cache simple de key -> value persistido en un archivo JSON. Lo usan
core/geocoder.py y core/poi_finder.py para no repetir, corrida tras
corrida, las mismas consultas a servicios externos con rate limits
ajustados (Nominatim: 1 req/seg; Overpass: uso "justo" y bastante
inestable) -- sin esto, cada corrida vuelve a geocodificar y a chequear
POIs para publicaciones que ya se procesaron antes, lo que multiplica
la chance de pegar contra un 429/406/timeout por las dudas.

Mismo approach que core/dedup.py: backend intencionalmente simple
(un JSON en disco); si el volumen crece mucho, reemplazar por sqlite u
otra cosa sin tocar la interfaz pública de esta clase.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DiskCache:
    def __init__(self, storage_path: str | Path | None = None):
        """
        storage_path: archivo JSON donde persistir las entradas entre
        corridas. Si es None, el cache es solo en memoria (útil para
        tests o corridas puntuales que no deben tocar disco).
        """
        self.storage_path = Path(storage_path) if storage_path else None
        self._data: dict[str, Any] = self._load()
        self._dirty = False

    def _load(self) -> dict[str, Any]:
        if not self.storage_path or not self.storage_path.exists():
            return {}
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("el archivo de cache no contiene un dict JSON")
            return data
        except Exception as e:
            # Si el archivo está corrupto, arrancamos de cero en vez de
            # tirar abajo todo el scraping -- preferible repetir alguna
            # consulta a perder la corrida entera.
            logger.error(
                f"No se pudo leer el cache ({self.storage_path}), arranco vacío: {e}",
                exc_info=True,
            )
            return {}

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._dirty = True

    def persist(self) -> None:
        if not self.storage_path or not self._dirty:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            self.storage_path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            self._dirty = False
        except Exception as e:
            logger.error(
                f"No se pudo persistir el cache ({self.storage_path}): {e}",
                exc_info=True,
            )
