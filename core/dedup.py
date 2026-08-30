"""
Deduplicación de publicaciones (Listing). Dos niveles:

1. Intra-batch: evita duplicados si un mismo sitio repite resultados
   entre páginas (pasa seguido con paginación mal sincronizada, o si
   una publicación se re-ordena entre el pedido de la página N y N+1).
2. Entre corridas: persiste las keys ya vistas en un archivo JSON
   simple, para no volver a notificar/escribir una publicación que ya
   viste en una corrida anterior. Es un backend intencionalmente
   simple: si el volumen crece mucho, reemplazar por una DB (sqlite,
   redis, etc.) sin tener que tocar la interfaz pública de esta clase.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

from core.models import Listing

logger = logging.getLogger(__name__)


class Deduplicator:
    def __init__(self, storage_path: str | Path | None = None):
        """
        storage_path: archivo JSON donde persistir las keys ya vistas
        entre corridas. Si es None, la dedup es solo intra-batch (no
        persiste nada a disco, útil para tests o corridas puntuales).
        """
        self.storage_path = Path(storage_path) if storage_path else None
        self._seen: set[str] = self._load()

    def _load(self) -> set[str]:
        if not self.storage_path or not self.storage_path.exists():
            return set()
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("el archivo de dedup no contiene una lista JSON")
            return set(data)
        except Exception as e:
            # Si el archivo está corrupto, arrancamos de cero en vez de
            # tirar abajo todo el scraping. Preferible duplicar alguna
            # notificación a perder la corrida entera.
            logger.error(
                f"No se pudo leer el archivo de dedup ({self.storage_path}), arranco vacío: {e}",
                exc_info=True,
            )
            return set()

    def _persist(self) -> None:
        if not self.storage_path:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            self.storage_path.write_text(
                json.dumps(sorted(self._seen), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(
                f"No se pudo persistir el archivo de dedup ({self.storage_path}): {e}",
                exc_info=True,
            )

    def filter_new(self, listings: Iterable[Listing], persist: bool = True) -> list[Listing]:
        """
        Devuelve solo las publicaciones cuya dedup_key no fue vista
        antes (ni en este batch, ni en corridas anteriores si hay
        storage_path). Actualiza el set interno y, si persist=True,
        lo escribe a disco al final.
        """
        listings = list(listings)  # por si llega un generador; lo necesitamos dos veces (loop + log)
        nuevas: list[Listing] = []
        vistas_este_batch: set[str] = set()

        for listing in listings:
            key = listing.dedup_key
            if key in self._seen or key in vistas_este_batch:
                continue
            vistas_este_batch.add(key)
            nuevas.append(listing)

        self._seen |= vistas_este_batch

        if persist and vistas_este_batch:
            self._persist()

        logger.info(f"Dedup: {len(nuevas)} nuevas de {len(listings)} totales")
        return nuevas

    def reset(self) -> None:
        """Limpia el estado en memoria (no borra el archivo persistido)."""
        self._seen = set()