import json
import logging
import re
import time

from sites.base import Scraper

logger = logging.getLogger(__name__)


class ZonapropScraper(Scraper):
    nombre_sitio = "zonaprop"

    def __init__(self, session, initial_url: str):
        super().__init__(session)
        self.initial_url = initial_url
        self.domain = "https://www.zonaprop.com.ar"

    def _next_page_url(self, page_number: int) -> str:
        base_path = re.sub(r'-pagina-\d+\.html$', '', self.initial_url)
        base_path = re.sub(r'\.html$', '', base_path)
        return f"{base_path}-pagina-{page_number}.html"

    def fetch_listings(self) -> list[dict]:
        """
        Itera sobre la paginación extrayendo el JSON del __PRELOADED_STATE__.
        Retorna la lista cruda acumulada de todas las páginas.
        """
        current_url = self.initial_url
        current_page = 1
        total_pages = 1
        publicaciones_crudas = []

        while current_page <= total_pages:
            logger.info("[%s] Fetching página %s/%s", self.nombre_sitio, current_page, total_pages)

            try:
                response = self.session.get(current_url)
                response.raise_for_status()
            except Exception:
                logger.exception("[%s] error fetching página %s", self.nombre_sitio, current_url)
                break

            marker = "window.__PRELOADED_STATE__ = "
            start = response.text.find(marker)
            if start == -1:
                logger.error("[%s] No se encontró el JSON en %s", self.nombre_sitio, current_url)
                break

            json_blob = response.text[start + len(marker):]
            try:
                state_data, _ = json.JSONDecoder().raw_decode(json_blob.lstrip())
            except json.JSONDecodeError:
                match = re.search(r'(\{.*\})\s*;\s*(?:</script>|$)', json_blob, re.DOTALL)
                if not match:
                    logger.exception("[%s] JSON inválido en %s", self.nombre_sitio, current_url)
                    break
                try:
                    state_data = json.loads(match.group(1))
                except json.JSONDecodeError:
                    logger.exception("[%s] JSON inválido en %s", self.nombre_sitio, current_url)
                    break

            list_store = state_data.get('listStore', {}) if isinstance(state_data, dict) else {}
            postings = list_store.get('listPostings', []) if isinstance(list_store, dict) else []
            publicaciones_crudas.extend(postings)

            paging = list_store.get('paging', {}) if isinstance(list_store, dict) else {}
            total_pages = paging.get('totalPages', 1) if isinstance(paging, dict) else 1

            if current_page < total_pages:
                current_url = self._next_page_url(current_page + 1)

            current_page += 1
            time.sleep(2)

        return publicaciones_crudas

    def parse_listing(self, raw: dict) -> dict:
        """
        Toma una publicación cruda del JSON y la lleva al formato normalizado.
        """
        price_operation_types = raw.get('priceOperationTypes') or []
        precio_obj = {}
        if isinstance(price_operation_types, list):
            for item in price_operation_types:
                if not isinstance(item, dict):
                    continue
                prices = item.get('prices') or []
                if isinstance(prices, list) and prices:
                    candidate = prices[0]
                    if isinstance(candidate, dict):
                        precio_obj = candidate
                        break

        expensas_obj = raw.get('expenses') or {}
        features = raw.get('mainFeatures') or {}
        ubicacion_dict = raw.get('postingLocation') or {}
        location = ubicacion_dict.get('location') or {}
        geolocation = {}
        posting_geolocation = ubicacion_dict.get('postingGeolocation') or {}
        if isinstance(posting_geolocation, dict):
            geolocation = posting_geolocation.get('geolocation') or {}

        url = raw.get('url') or ""
        if url and not url.startswith("http"):
            url = f"{self.domain}{url}"

        return {
            "url": url,
            "precio": precio_obj.get('amount', 0),
            "moneda": precio_obj.get('currency', 'ARS'),
            "expensas": expensas_obj.get('amount', 0) if isinstance(expensas_obj, dict) else 0,
            "capacidad": features.get('CFT1', {}).get('value', 0) if isinstance(features, dict) else 0,
            "amueblado": False,
            "ubicacion": location.get('name', 'Desconocido'),
            "lat": geolocation.get('latitude'),
            "lon": geolocation.get('longitude'),
            "fecha_scrapeo": self._timestamp(),
            "sitio_origen": self.nombre_sitio,
        }