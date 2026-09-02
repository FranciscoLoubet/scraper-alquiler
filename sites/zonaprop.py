import json
import logging
import re
import time
from typing import Any

import requests

from sites.base import Scraper

logger = logging.getLogger(__name__)


class ZonapropScraper(Scraper):
    nombre_sitio = "zonaprop"
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    def __init__(self, session=None, initial_url: str = "", max_pages: int = 3, timeout: int = 20):
        """Inicializa el scraper con una sesión HTTP y la URL base de búsqueda.

        Args:
            session: sesión de requests u objeto compatible con `.get()`.
            initial_url: URL de la búsqueda inicial.
            max_pages: cantidad máxima de páginas a recorrer.
            timeout: timeout de cada request en segundos.
        """
        self.session = session or requests.Session()
        if not hasattr(self.session, "headers"):
            self.session.headers = {}
        self.session.headers.setdefault("User-Agent", self.DEFAULT_USER_AGENT)
        self.session.headers.setdefault("Accept-Language", "es-AR,es;q=0.9,en;q=0.8")
        # Headers que manda un browser real y requests no agrega solo.
        # Sin esto, algunos WAF (Akamai/Cloudflare/Datadome, etc.) tiran
        # 403 directo aunque el User-Agent esté bien seteado.
        self.session.headers.setdefault(
            "Accept",
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        )
        self.session.headers.setdefault("Accept-Encoding", "gzip, deflate, br")
        self.session.headers.setdefault("Upgrade-Insecure-Requests", "1")
        self.session.headers.setdefault("Sec-Fetch-Dest", "document")
        self.session.headers.setdefault("Sec-Fetch-Mode", "navigate")
        self.session.headers.setdefault("Sec-Fetch-Site", "none")
        self.initial_url = initial_url
        self.max_pages = max_pages
        self.timeout = timeout
        self.domain = "https://www.zonaprop.com.ar"
        self._sesion_calentada = False

    def _calentar_sesion(self) -> None:
        """
        Pide la home antes de la búsqueda para levantar las cookies que
        el WAF de ZonaProp exige en el request siguiente -- pedir la URL
        de búsqueda "en frío" (sin cookies previas) es lo que suele
        devolver 403. Si esto falla, seguimos igual: puede que el bloqueo
        sea por otra causa y no tiene sentido frenar todo el scraping acá.
        """
        if self._sesion_calentada:
            return
        self._sesion_calentada = True
        try:
            try:
                self.session.get(self.domain, timeout=self.timeout)
            except TypeError:
                self.session.get(self.domain)
            time.sleep(1.0)
        except Exception:
            logger.warning("[%s] no se pudo precalentar la sesión contra %s", self.nombre_sitio, self.domain)

    def _next_page_url(self, page_number: int) -> str:
        """Genera la URL de la siguiente página sin romper rutas ya paginadas."""
        if not self.initial_url:
            return ""

        base_path = re.sub(r'-pagina-\d+(\.html)?$', '', self.initial_url)
        base_path = re.sub(r'\.html$', '', base_path)
        base_path = base_path.split("?")[0]
        return f"{base_path}-pagina-{page_number}.html"

    def _extract_state_data(self, response_text: str, current_url: str) -> dict:
        """Extrae el JSON embebido de `__PRELOADED_STATE__` de la página HTML."""
        marker = "window.__PRELOADED_STATE__ = "
        start = response_text.find(marker)
        if start == -1:
            raise ValueError(f"No se encontró __PRELOADED_STATE__ en {current_url}")

        payload = response_text[start + len(marker):].strip()
        payload = payload.split("</script>", 1)[0].strip()
        if payload.endswith(";"):
            payload = payload[:-1].rstrip()

        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            match = re.search(r'(\{.*\})\s*;?\s*$', payload, re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(1))

    def fetch_listings(self) -> list[dict]:
        """Trae la lista de publicaciones crudas de la búsqueda actual.

        Recorre páginas consecutivas hasta llegar al límite configurado o a la última
        página disponible. Elimina duplicados por URL para evitar repeticiones dentro
        del mismo lote de scraping.
        """
        if not self.initial_url:
            raise ValueError("initial_url es obligatoria para ZonapropScraper")

        self._calentar_sesion()

        current_url = self.initial_url
        current_page = 1
        publicaciones_crudas: list[dict] = []
        seen_urls: set[str] = set()

        while current_page <= self.max_pages:
            logger.info("[%s] Fetching página %s", self.nombre_sitio, current_url)
            try:
                try:
                    response = self.session.get(current_url, timeout=self.timeout)
                except TypeError:
                    response = self.session.get(current_url)
                response.raise_for_status()
            except Exception:
                logger.exception("[%s] error fetching página %s", self.nombre_sitio, current_url)
                break

            try:
                state_data = self._extract_state_data(response.text, current_url)
            except Exception:
                logger.exception("[%s] JSON inválido en %s", self.nombre_sitio, current_url)
                break

            list_store = state_data.get("listStore", {}) if isinstance(state_data, dict) else {}
            postings = list_store.get("listPostings", []) if isinstance(list_store, dict) else []
            if not isinstance(postings, list):
                postings = []

            for posting in postings:
                if not isinstance(posting, dict):
                    continue
                posting_url = posting.get("url") or ""
                if not posting_url:
                    continue
                normalized_url = posting_url.strip().lower()
                if normalized_url in seen_urls:
                    continue
                seen_urls.add(normalized_url)
                publicaciones_crudas.append(posting)

            paging = list_store.get("paging", {}) if isinstance(list_store, dict) else {}
            total_pages = paging.get("totalPages", 1) if isinstance(paging, dict) else 1
            if current_page >= min(self.max_pages, int(total_pages)):
                break

            current_page += 1
            current_url = self._next_page_url(current_page)
            time.sleep(1.5)

        return publicaciones_crudas

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        """Convierte un valor a float con fallback seguro cuando viene vacío o inválido."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _extract_price(self, raw: dict) -> tuple[float, str]:
        """Extrae precio y moneda de la publicación cruda, priorizando estructuras JSON típicas."""
        price_operation_types = raw.get("priceOperationTypes") or []
        if isinstance(price_operation_types, list):
            for item in price_operation_types:
                if not isinstance(item, dict):
                    continue
                prices = item.get("prices") or []
                if isinstance(prices, list):
                    for price in prices:
                        if not isinstance(price, dict):
                            continue
                        amount = price.get("amount")
                        currency = (price.get("currency") or "ARS").upper()
                        if amount is not None:
                            return float(amount), currency

        price_field = raw.get("price")
        if isinstance(price_field, dict):
            amount = price_field.get("amount")
            currency = (price_field.get("currency") or "ARS").upper()
            if amount is not None:
                return float(amount), currency

        for key in ("precio", "price", "amount"):
            value = raw.get(key)
            if isinstance(value, (int, float, str)):
                return float(value), "ARS"

        return 0.0, "ARS"

    def _extract_capacidad(self, raw: dict) -> float:
        """Intenta localizar la cantidad de ambientes/capacidad si el sitio la expone."""
        features = raw.get("mainFeatures") or {}
        if isinstance(features, dict):
            for key in ("CFT1", "ambientes", "rooms", "bedrooms"):
                value = features.get(key)
                if isinstance(value, dict):
                    candidate = value.get("value")
                    if candidate is not None:
                        return self._to_float(candidate)
                elif isinstance(value, (int, float, str)):
                    return self._to_float(value)

        metadata = raw.get("metadata") or {}
        if isinstance(metadata, dict):
            for key in ("ambientes", "rooms"):
                value = metadata.get(key)
                if value is not None:
                    return self._to_float(value)

        return 0.0

    def _extract_amueblado(self, raw: dict) -> bool | None:
        """Detecta si la publicación menciona que está amoblada o no, usando texto libre como fallback."""
        explicit = raw.get("amueblado")
        if isinstance(explicit, bool):
            return explicit

        text = " ".join(
            str(part)
            for part in (
                raw.get("title"),
                raw.get("description"),
                raw.get("titulo"),
                raw.get("descripcion"),
                raw.get("text"),
            )
            if part is not None
        ).lower()

        if not text:
            return None

        keywords = ("amueblado", "amoblado", "amueblada", "amoblada", "muebles", "mobiliado")
        return any(keyword in text for keyword in keywords)

    def _extract_location(self, raw: dict) -> str:
        """Retorna la zona o dirección textual que ofrece el sitio para la publicación."""
        posting_location = raw.get("postingLocation") or {}
        if isinstance(posting_location, dict):
            location = posting_location.get("location") or {}
            if isinstance(location, dict):
                name = location.get("name")
                if name:
                    return str(name)

        for key in ("location", "zona", "direccion", "address", "title"):
            value = raw.get(key)
            if isinstance(value, dict):
                candidate = value.get("name") or value.get("address") or value.get("label")
                if candidate:
                    return str(candidate)
            elif value:
                return str(value)

        return "Desconocido"

    def _extract_geolocation(self, raw: dict) -> tuple[float | None, float | None]:
        """Busca latitud y longitud dentro del JSON embebido de la publicación."""
        posting_location = raw.get("postingLocation") or {}
        geolocation = {}
        if isinstance(posting_location, dict):
            nested = posting_location.get("postingGeolocation") or {}
            if isinstance(nested, dict):
                geolocation = nested.get("geolocation") or {}

        if not geolocation and isinstance(raw.get("geolocation"), dict):
            geolocation = raw["geolocation"]

        lat = geolocation.get("latitude") if isinstance(geolocation, dict) else None
        lon = geolocation.get("longitude") if isinstance(geolocation, dict) else None
        if lat is not None:
            lat = float(lat)
        if lon is not None:
            lon = float(lon)
        return lat, lon

    def parse_listing(self, raw: dict) -> dict:
        """Convierte una publicación cruda de ZonaProp a un dict normalizado.

        La salida intenta seguir el contrato base del scraper: incluye los campos
        mínimos necesarios para el resto del pipeline (precio, moneda, capacidad,
        amueblado, ubicación, URL, coordenadas y metadatos del scrape).
        """
        if not isinstance(raw, dict):
            raise ValueError("raw debe ser un dict")

        precio, moneda = self._extract_price(raw)
        lat, lon = self._extract_geolocation(raw)
        url = raw.get("url") or ""
        if url and not url.startswith("http"):
            url = f"{self.domain}{url}"

        return {
            "url": url,
            "precio": precio,
            "moneda": moneda,
            "expensas": 0,
            "capacidad": self._extract_capacidad(raw),
            "amueblado": self._extract_amueblado(raw),
            "ubicacion": self._extract_location(raw),
            "lat": lat,
            "lon": lon,
            "fecha_scrapeo": self._timestamp(),
            "sitio_origen": self.nombre_sitio,
        }