import re
import json
import time
import logging
from base import Scraper  # Tu clase base

logger = logging.getLogger(__name__)

class ZonapropScraper(Scraper):
    nombre_sitio = "zonaprop"

    def __init__(self, session, initial_url: str):
        super().__init__(session)
        self.initial_url = initial_url
        self.domain = "https://www.zonaprop.com.ar"

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
            logger.info(f"[{self.nombre_sitio}] Fetching página {current_page}/{total_pages}")
            
            # Asumimos que session es un requests.Session u objeto similar con método .get()
            response = self.session.get(current_url)
            response.raise_for_status()
            
            match = re.search(r'window\.__PRELOADED_STATE__ = (\{.*?\});', response.text, re.DOTALL)
            if not match:
                logger.error(f"[{self.nombre_sitio}] No se encontró el JSON en {current_url}")
                break
                
            state_data = json.loads(match.group(1))
            list_store = state_data.get('listStore', {})
            postings = list_store.get('listPostings', [])
            
            publicaciones_crudas.extend(postings)

            # Lógica de paginación
            paging = list_store.get('paging', {})
            total_pages = paging.get('totalPages', 1)
            
            if current_page < total_pages:
                base_path = self.initial_url.replace(".html", "")
                base_path = re.sub(r'-pagina-\d+', '', base_path)
                current_url = f"{base_path}-pagina-{current_page + 1}.html"
            
            current_page += 1
            time.sleep(2)  # Delay para evitar rate-limiting
            
        return publicaciones_crudas

    def parse_listing(self, raw: dict) -> dict:
        """
        Toma una publicación cruda del JSON y la lleva al formato normalizado.
        """
        # Extracción segura usando .get()
        precio_obj = raw.get('priceOperationTypes', [{}])[0].get('prices', [{}])[0]
        expensas_obj = raw.get('expenses') or {}
        features = raw.get('mainFeatures', {})
        ubicacion_dict = raw.get('postingLocation', {})
        
        # Mapeo al contrato
        return {
            "url": f"{self.domain}{raw.get('url', '')}",
            "precio": precio_obj.get('amount', 0),
            "moneda": precio_obj.get('currency', 'ARS'),
            "expensas": expensas_obj.get('amount', 0),
            "capacidad": features.get('CFT1', {}).get('value', 0), # Ambientes
            "amueblado": False, # Zonaprop no siempre lo expone fácil, requiere iterar features
            "ubicacion": ubicacion_dict.get('location', {}).get('name', 'Desconocido'),
            "lat": ubicacion_dict.get('postingGeolocation', {}).get('geolocation', {}).get('latitude'),
            "lon": ubicacion_dict.get('postingGeolocation', {}).get('geolocation', {}).get('longitude'),
            "fecha_scrapeo": self._timestamp(),
            "sitio_origen": self.nombre_sitio
        }