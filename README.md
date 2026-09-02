# scraper-alquiler

Bot que scrapea publicaciones de alquiler (por ahora, ZonaProp), las
filtra según criterios propios (ubicación/tiempo a la universidad,
transporte público, supermercado y gimnasio cerca, precio, ambientes,
amueblado) y escribe las nuevas coincidencias a una Google Sheet.

## Cómo funciona (pipeline)

```
sites/*.py          -> scrapea el sitio, devuelve dicts crudos
core/normalizer.py  -> convierte los dicts crudos a Listing (core/models.py)
core/filters.py     -> aplica precio/ambientes/amueblado (config/criterios.yaml)
core/geocoder.py    -> geocodifica ubicaciones sin lat/lon (Nominatim/OSM)
core/poi_finder.py  -> chequea distancia a la universidad + POIs obligatorios (Overpass/OSM)
core/dedup.py       -> descarta publicaciones ya notificadas en corridas anteriores
notifiers/sheets_writer.py -> escribe las publicaciones nuevas a Google Sheets
```

Todo se orquesta desde `main.py`.

## Setup

1. Crear un virtualenv e instalar dependencias:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   playwright install --with-deps chromium
   ```
   El último paso descarga el Chromium que usa `utils/browser.py` para
   scrapear ZonaProp -- el sitio está detrás de Cloudflare y exige
   resolver un challenge en JavaScript, que un cliente HTTP simple
   como `requests` no puede resolver por más headers de navegador que
   se le agreguen.
2. Crear una Service Account en Google Cloud, descargar su JSON de
   credenciales, y compartir la Google Sheet destino con el email de
   esa service account (como Editor).
3. Copiar `.env.example` a `.env` y completar:
   - `GOOGLE_SHEETS_SPREADSHEET_ID`: el ID de la spreadsheet (está en
     su URL).
   - `GOOGLE_SHEETS_CREDENTIALS_PATH`: ruta al JSON de la service
     account.
4. Ajustar `config/criterios.yaml` si los criterios cambian (zona de
   referencia, radios de POI, precio, etc.).
5. Correr:
   ```bash
   python main.py
   ```

## Correr los tests

```bash
python -m unittest discover -s tests
```

## Automatización

`.github/workflows/scrape.yml` corre `main.py` cada 6 horas vía GitHub
Actions. Requiere configurar estos secrets en el repo:

- `GOOGLE_SHEETS_SPREADSHEET_ID`
- `GOOGLE_SHEETS_CREDENTIALS_JSON` (el contenido completo del JSON de
  la service account, pegado como secret)

El estado de deduplicación (`data/vistos.json`) se commitea de vuelta
al repo al final de cada corrida exitosa, para no volver a notificar
la misma publicación en la corrida siguiente.

## Estructura

- `sites/`: un scraper por sitio (contrato abstracto en `sites/base.py`).
- `core/`: modelo de datos y lógica de negocio (filtros, dedup, geocoding, POIs).
- `notifiers/`: salida de las publicaciones filtradas (por ahora, Google Sheets).
- `config/criterios.yaml`: criterios de filtrado configurables sin tocar código.
- `utils/`: utilidades compartidas (sesión HTTP con throttling).
