# Licencias y corpus · Fototeca Viva

Origen, licencia y uso de cada fuente de datos, de cada modelo y de cada componente de terceros. Las licencias
se confirmaron en la página de origen el **2026-11-07** (H0, verificación 0.8; evidencia textual en
`evaluacion/resultados/h0.json` → `verificaciones.0.8`). Solo se usan las fuentes que lista este documento, las
mismas que declara `servicio/config/fuentes.yaml`. **Ninguna** fuente se descarga de YouTube ni de sitios fuera de
esa lista.

## 1. Corpus de fotos

| Fuente | URL | Licencia confirmada | Uso en el proyecto |
|---|---|---|---|
| **Crossmodal-3600 (XM3600): imágenes** | `https://open-images-dataset.s3.amazonaws.com/crossmodal-3600/images.tgz` | Las imágenes provienen de Open Images, que las lista con licencia **CC BY 2.0**; la atribución de cada imagen está en `image_attributions.csv` | El archivo fotográfico: 3,600 fotos de 36 locales (100 por locale) |
| **XM3600: descripciones** | `https://google.github.io/crossmodal-3600/web-data/captions.zip` | **CC BY 4.0** — «The annotations are licensed by Google LLC under CC BY 4.0 license» (página del proyecto) | Descripciones de referencia en español (2 a 4 por imagen): fichas iniciales del archivo, evaluación y consultas de búsqueda |
| **XM3600: atribuciones** | `https://google.github.io/crossmodal-3600/web-data/image_attributions.csv` | — (metadatos de atribución) | Cita por imagen (autor y licencia de cada foto) |
| **Open Images V7: etiquetas por imagen verificadas por humanos** | `https://storage.googleapis.com/openimages/v7/oidv7-{train,val,test}-annotations-human-imagelabels.csv` y `oidv7-class-descriptions.csv` (tomadas de `download_v7.html`) | Anotaciones **CC BY 4.0** (Google LLC); imágenes listadas como **CC BY 2.0** (`factsfigures_v7.html`) | Referencia para evaluar palabras clave y para las palabras clave de las fichas iniciales. Los CSV completos (2,857,815,256 bytes entre los tres; `h0.json` → `0.7.open_images.originales`) se leen en *streaming* y solo se guardan las filas de las 3,600 imágenes de XM3600 |

**Atribución de las fotos:** cada foto de XM3600 conserva su atribución individual (autor, licencia y URL) en
`data/crudos/xm3600/image_attributions.csv`. Las fotos **no se versionan** en el repositorio (se descargan con
`scripts/preparar_datos.py`); las que aparezcan en el informe o en la presentación llevan su atribución.

**Datos personales:** ninguna de las 3,600 fotos trae EXIF (H0, 0.7), así que no hay coordenadas GPS en el
corpus. Para probar el guardrail de EXIF se generan 20 copias con GPS **sintético** (`gps_sintetico`). Las
consultas de prueba con datos personales usan datos **ficticios**.

## 2. Corpus normativo

| Fuente | URL | Licencia confirmada | Uso |
|---|---|---|---|
| **IPTC Photo Metadata Standard 2025.1** | `http://iptc.org/std/photometadata/specification/IPTC-PhotoMetadata-2025.1.html` | **CC BY 4.0** — «published under the Creative Commons Attribution 4.0 license» | Definición de los campos (Alt Text, Headline, Description, Extended Description, Keywords…): una propiedad por fragmento |
| **W3C WAI · Images Tutorial** (10 páginas: índice, decorativas, informativas, funcionales, de texto, complejas, grupos, mapas de imagen, árbol de decisión y consejos) | `https://www.w3.org/WAI/tutorials/images/…` | **W3C Document License** — «See Permission to Use WAI Material» | Reglas para escribir texto alternativo. No hay traducción al español (las rutas `/es` responden 404), así que se usa la versión en inglés, como permite `04` |
| **WCAG 2.2 · Understanding 1.1.1 Non-text Content** | `https://www.w3.org/WAI/WCAG22/Understanding/non-text-content` | **W3C Document License** («Permission to Use WAI Material») | Criterio de conformidad 1.1.1 y técnicas |
| **DCMI Metadata Terms** | `https://www.dublincore.org/specifications/dublin-core/dcmi-terms/` | **CC BY 4.0** — enlace `rel="license"` a «Creative Commons Attribution 4.0 International License» | Elementos descriptivos (title, description, subject…): un término por fragmento |
| **Tesauro de la UNESCO** (SKOS) | `https://vocabularies.unesco.org/exports/thesaurus/latest/unesco-thesaurus.ttl` | **CC BY-SA 3.0 IGO** — «available for download in open data formats under a CC BY-SA 3.0 IGO licence» | Vocabulario controlado en español (`prefLabel`, `altLabel` y `scopeNote` con `@es`): un concepto por documento |

**Nota sobre CC BY-SA:** el tesauro se usa como vocabulario de referencia; si se redistribuyera un derivado del
tesauro, tendría que llevar la misma licencia. El repositorio no versiona el volcado (se descarga en la preparación).

**Tamaño del corpus normativo y cumplimiento de R1** (`evaluacion/resultados/corpus_r1.json`, versión del
corpus `e1879cf60262`): 13 documentos fuente (1 de IPTC, 10 páginas del tutorial de W3C, 1 de WCAG y 1 de DCMI);
412 fragmentos y 177,118 caracteres, es decir, **88.6 páginas aproximadas** (2,000 caracteres por página) **sin
contar el tesauro**. R1 se cumple por el criterio de 50 páginas. El tesauro aporta 4,500 conceptos, todos con
etiqueta en español (ninguno descartado). El corpus de fotos (XM3600) se cuenta aparte.

## 3. Modelos (todos servidos localmente con Ollama `0.40.15`)

| Rol | Tag de Ollama | Licencia | Fuente de la licencia |
|---|---|---|---|
| Visión y composición de las fichas (P1, P2 y P3) | `qwen3.5:0.8b` | **Apache 2.0** | `ollama show` (campo `license`, H0 0.8) |
| Búsquedas complejas (P4, P5) y respaldo de P3 | `lfm3:1.7b-q4_K_M` | **LFM Open License v1.0** (Liquid AI) | `ollama show` y ficha de Ollama |
| Memoria multimodal (embeddings) | `embeddinggemma-2:440m` | **Apache 2.0** | Ficha oficial `huggingface.co/google/embeddinggemma-2` (`license: apache-2.0`); `ollama show` no incluye el texto |
| Auditor y segundo embedding | `granite-embedding:278m` | **Apache 2.0** (IBM) | `ollama show` |

[AUTOR: revisar que la LFM Open License v1.0 permita el uso académico previsto; el texto completo se obtiene con
`docker compose exec ollama ollama show lfm3:1.7b-q4_K_M --license`.]

## 4. Software de terceros incluido o usado en tiempo de ejecución

| Componente | Versión | Licencia | Dónde |
|---|---|---|---|
| Swagger UI (`swagger-ui-dist`) | 5.34.0 | Apache 2.0 | `servicio/fototeca/api/estaticos/` (assets locales para `/docs` sin red; integridad sha512 verificada contra npm) |
| Imágenes Docker | `ollama/ollama:0.40.15`, `qdrant/qdrant:v1.19.2`, `python:3.12.16-slim-bookworm`, `nginx:1.30.6-alpine`, `ghcr.io/astral-sh/uv:0.13.5` | Ollama: MIT · Qdrant: Apache 2.0 · uv: Apache 2.0 · nginx: BSD-2-Clause (campo `license` de la API de GitHub de cada repositorio, consultado el 2026-11-07) · CPython: licencia propia de la PSF (GitHub la reporta como «Other») | `docker-compose.yml`, `servicio/Dockerfile` |
| Paquetes de Python | ver `servicio/uv.lock` y `servicio/requirements.txt` | Tabla siguiente | Imagen `servicio` |

### Paquetes de Python instalados en la imagen `servicio` (51)

Generada con `docker compose run --rm servicio python -m scripts.licencias_paquetes` a partir de los metadatos de cada paquete instalado (`License-Expression`, `License` o los clasificadores «License ::»); el detalle, con el campo de origen, está en `evaluacion/resultados/licencias_paquetes.json`. Ninguna es copyleft fuerte: son MIT, BSD, Apache 2.0, PSF, MIT-CMU, CNRI-Python y, dentro de numpy, 0BSD, Zlib y CC0. La única de copyleft débil es MPL 2.0 (`certifi`, por archivo), que se usa sin modificar.

| Paquete | Versión | Licencia (metadatos) |
|---|---|---|
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| beautifulsoup4 | 4.15.0 | MIT License |
| certifi | 2026.10.23 | MPL-2.0 |
| click | 8.5.0 | BSD-3-Clause |
| colorama | 0.4.6 | BSD License |
| contourpy | 1.4.0 | BSD-3-Clause |
| cycler | 0.12.1 | BSD License |
| fastapi | 0.162.0 | MIT |
| fonttools | 4.67.0 | MIT |
| grimp | 3.17 | BSD 2-Clause License |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| import-linter | 2.15 | BSD 2-Clause License |
| iniconfig | 2.3.1 | MIT |
| kiwisolver | 1.5.1 | BSD License |
| lxml | 6.1.3 | BSD-3-Clause |
| markdown-it-py | 4.2.0 | MIT License |
| matplotlib | 3.11.2 | Python Software Foundation License |
| mdurl | 0.1.2 | MIT License |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| opentelemetry-api | 1.45.1 | Apache-2.0 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| piexif | 1.1.3 | MIT |
| pillow | 13.0.0 | MIT-CMU |
| pluggy | 1.7.0 | MIT |
| portalocker | 4.4.1 | BSD-3-Clause |
| pydantic | 2.14.1 | MIT |
| pydantic_core | 2.50.1 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| pyparsing | 3.3.3 | MIT |
| pypdf | 6.21.2 | BSD-3-Clause |
| pytest | 9.1.1 | MIT |
| python-dateutil | 3.0.0 | Dual License |
| python-multipart | 0.0.32 | Apache-2.0 |
| PyYAML | 6.0.3 | MIT |
| rdflib | 7.6.0 | BSD-3-Clause |
| regex | 2026.9.29 | Apache-2.0 AND CNRI-Python |
| rich | 15.0.0 | MIT |
| sacrebleu | 2.6.0 | Apache-2.0 |
| six | 1.17.0 | MIT |
| soupsieve | 3.0.4 | MIT |
| starlette | 1.9.0 | BSD-3-Clause |
| tabulate | 0.10.0 | MIT |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| tzdata | 2026.5 | Apache-2.0 |
| uvicorn | 0.54.0 | BSD-3-Clause |
