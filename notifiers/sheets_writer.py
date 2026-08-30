"""
notifiers/sheets_writer.py

Escribe publicaciones (Listing) a una Google Sheet usando gspread +
credenciales de service account.

Requiere:
    pip install gspread google-auth

Y un archivo de credenciales de service account (JSON, descargado desde
Google Cloud Console) compartido como Editor sobre la planilla destino
-- si no compartís la planilla con el email del service account
(algo así como xxx@yyy.iam.gserviceaccount.com), esto va a fallar con
un 403 al primer intento de escritura.
"""

from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Any, Iterable

from core.models import Listing

logger = logging.getLogger(__name__)

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None
    Credentials = None
    logger.warning(
        "gspread / google-auth no están instalados. Corré: pip install gspread google-auth"
    )

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# La API de Google Sheets limita por defecto a 60 requests de escritura
# por minuto por usuario (y 300/min por proyecto). Estos valores son
# para manejar ese límite sin que el proceso explote:
MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 2  # espera 2, 4, 8, 16, 32s (+ jitter) entre reintentos
MIN_SECONDS_BETWEEN_WRITES = 1.0  # throttle propio, para no ni acercarse al límite


class SheetsWriter:
    def __init__(
        self,
        credentials_path: str | Path,
        spreadsheet_id: str,
        worksheet_name: str = "Publicaciones",
    ):
        if gspread is None or Credentials is None:
            raise ImportError("Falta instalar gspread y google-auth para usar SheetsWriter")

        self.credentials_path = Path(credentials_path)
        if not self.credentials_path.exists():
            raise FileNotFoundError(
                f"No se encontró el archivo de credenciales: {self.credentials_path}"
            )

        self.spreadsheet_id = spreadsheet_id
        self.worksheet_name = worksheet_name

        creds = Credentials.from_service_account_file(str(self.credentials_path), scopes=SCOPES)
        self._client = gspread.authorize(creds)

        try:
            self._spreadsheet = self._client.open_by_key(self.spreadsheet_id)
        except gspread.exceptions.APIError as e:
            logger.error(
                f"No se pudo abrir la spreadsheet {self.spreadsheet_id}. "
                f"¿Está compartida con el service account como Editor? Detalle: {e}"
            )
            raise

        self._worksheet = self._get_or_create_worksheet()
        self._ultima_escritura: float = 0.0

    def _get_or_create_worksheet(self):
        try:
            ws = self._spreadsheet.worksheet(self.worksheet_name)
        except gspread.WorksheetNotFound:
            logger.info(f"Hoja '{self.worksheet_name}' no existe, la creo")
            ws = self._spreadsheet.add_worksheet(
                title=self.worksheet_name,
                rows=1000,
                cols=len(Listing.HEADERS) + 2,
            )
        self._ensure_headers(ws)
        return ws

    def _ensure_headers(self, ws) -> None:
        primer_fila = ws.row_values(1)
        if primer_fila != Listing.HEADERS:
            ws.update("A1", [Listing.HEADERS])

    @staticmethod
    def _row_for_sheets(listing: Listing) -> list[Any]:
        """
        to_row() puede traer None (lat/lon faltantes, amueblado sin
        dato). Enviar None crudo a la API de Sheets es riesgoso según
        la versión de gspread (a veces termina como el string literal
        "None" en la celda, en vez de vacío). Lo convertimos acá a ""
        para que la celda quede realmente vacía.
        """
        return ["" if v is None else v for v in listing.to_row()]

    @staticmethod
    def _es_error_de_cuota(e: "gspread.exceptions.APIError") -> bool:
        """
        gspread no tiene un tipo de excepción separado para 'cuota
        excedida' -- viene como un APIError genérico. Hay que mirar el
        status code y/o el mensaje para distinguirlo de otros errores
        (permisos, spreadsheet no encontrada, etc.) que NO conviene
        reintentar.
        """
        status = getattr(getattr(e, "response", None), "status_code", None)
        mensaje = str(e)
        return status == 429 or "RESOURCE_EXHAUSTED" in mensaje or "Quota exceeded" in mensaje

    def _throttle(self) -> None:
        """Espera lo necesario para no escribir más seguido que MIN_SECONDS_BETWEEN_WRITES."""
        transcurrido = time.monotonic() - self._ultima_escritura
        falta = MIN_SECONDS_BETWEEN_WRITES - transcurrido
        if falta > 0:
            time.sleep(falta)

    def _append_con_reintentos(self, filas: list[list[Any]]) -> None:
        intento = 0
        while True:
            self._throttle()
            try:
                self._worksheet.append_rows(filas, value_input_option="USER_ENTERED")
                self._ultima_escritura = time.monotonic()
                return
            except gspread.exceptions.APIError as e:
                self._ultima_escritura = time.monotonic()

                if not self._es_error_de_cuota(e) or intento >= MAX_RETRIES:
                    logger.error(
                        f"Error escribiendo a Google Sheets (intento {intento + 1}/{MAX_RETRIES + 1}): {e}",
                        exc_info=True,
                    )
                    raise

                espera = BACKOFF_BASE_SECONDS * (2 ** intento) + random.uniform(0, 1)
                logger.warning(
                    f"Cuota de Google Sheets excedida, reintento {intento + 1}/{MAX_RETRIES} "
                    f"en {espera:.1f}s"
                )
                time.sleep(espera)
                intento += 1

    def write(self, listings: Iterable[Listing]) -> int:
        """
        Agrega las publicaciones al final de la hoja en un solo
        request batch (append_rows), en vez de una llamada por fila
        -- la API de Sheets tiene rate limits ajustados (falla
        rápido con muchas publicaciones si escribís de a una).

        Maneja la cuota de dos formas:
        1. Throttle propio (MIN_SECONDS_BETWEEN_WRITES) antes de cada
           request, para no acercarse al límite en primer lugar.
        2. Reintentos con backoff exponencial si, aun así, la API
           responde con error de cuota (429 / RESOURCE_EXHAUSTED).
           Otros errores (permisos, spreadsheet inexistente, etc.) NO
           se reintentan -- se propagan al instante.

        Devuelve la cantidad de filas efectivamente escritas.

        No hace dedup acá: se asume que las listings que llegan ya
        pasaron por core/dedup.py. Si le pasás una lista con
        duplicados, los va a escribir igual.
        """
        listings = list(listings)
        if not listings:
            logger.info("SheetsWriter: nada para escribir")
            return 0

        filas = [self._row_for_sheets(listing) for listing in listings]
        self._append_con_reintentos(filas)

        logger.info(f"SheetsWriter: {len(filas)} filas agregadas a '{self.worksheet_name}'")
        return len(filas)