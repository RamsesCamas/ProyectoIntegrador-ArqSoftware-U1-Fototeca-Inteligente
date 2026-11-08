# Fototeca Viva

**Catalogación accesible y trazable de archivos fotográficos.** Por cada foto genera una ficha catalográfica IPTC
(titular, descripción, texto alternativo de 250 caracteres o menos, descripción extendida y palabras clave del
Tesauro de la UNESCO) en la que **cada campo indica su fuente**; detecta casi duplicados; busca por texto en español
o por foto, explicando cada coincidencia; y **aprende de las correcciones del archivista sin fine-tuning**.

Proyecto integrador de la Unidad II de Tópicos Selectos de Arquitectura de Software (MCIT, UPChiapas).
Todo corre **en local, en CPU y sin servicios en la nube**: modelos en Ollama, base vectorial Qdrant, servicio
FastAPI en capas y una web estática que solo habla con la API.

> Las fichas y los resultados los generan modelos de IA y pueden contener errores. Revísalos antes de publicarlos.

## Requisitos

- **Docker Desktop** (Windows, macOS o Linux) con **8 GB o más de memoria** asignados y espacio libre en disco para
  las imágenes Docker, los modelos y los datos (pendiente: la cifra medida se agrega en H9).
  Es lo único que necesita el equipo: todos los scripts se ejecutan dentro de contenedores.
- Internet **solo para la preparación** (imágenes Docker, modelos, datos y corpus). Después, todo funciona sin red.

## Comandos

```bash
# Preparación (con internet)
docker compose --profile preparacion run --rm modelos          # descarga los 4 modelos
docker compose run --rm servicio python -m scripts.verificar_h0
docker compose run --rm servicio python -m scripts.preparar_datos
docker compose run --rm servicio python -m scripts.preparar_corpus
docker compose run --rm servicio python -m scripts.indexar_archivo

# Operación (sin internet)
docker compose up -d
#   Web:       http://localhost:8080
#   API docs:  http://localhost:8000/docs

# Evaluación y pruebas
docker compose run --rm servicio python -m evaluacion.ejecutar_todo
docker compose run --rm servicio pytest -q
```

Crear un archivo `.env` es **opcional**: `docker-compose.yml` ya trae los valores de `.env.ejemplo`.

## Modelos (todos servidos por Ollama `0.40.15`, en CPU)

| Rol | Tag | Licencia |
|---|---|---|
| Visión y ruta rápida | `qwen3.5:0.8b` | Apache 2.0 |
| Catalogador y ruta capaz | `lfm3:1.7b-q4_K_M` | LFM Open License v1.0 |
| Memoria multimodal (embeddings de texto e imagen) | `embeddinggemma-2:440m` | Apache 2.0 |
| Auditor y segundo embedding | `granite-embedding:278m` | Apache 2.0 |

`embeddinggemma-2:270m` no acepta imágenes en Ollama; por eso se usa `440m` (ver `docs/adr/ADR-10-*.md`).

## Solución de problemas

- **El contenedor `ollama` no arranca: «ports are not available … 11434».** El equipo ya tiene Ollama instalado de
  forma nativa usando ese puerto. Ciérralo, o crea un archivo `.env` con `OLLAMA_PUERTO_HOST=11435` (el puerto del
  host solo sirve para diagnóstico; el servicio usa la red interna de Docker). Lo mismo para Qdrant con
  `QDRANT_PUERTO_HOST`.
- **Memoria en Windows (Docker Desktop con WSL 2).** Docker Desktop toma la memoria que le asigna WSL. Si al levantar
  los contenedores alguno se reinicia por falta de memoria, crea `%UserProfile%\.wslconfig` con:

  ```ini
  [wsl2]
  memory=8GB
  ```

  y reinicia WSL (`wsl --shutdown`) y Docker Desktop. Los límites de los contenedores suman 7.1 GB.
- **La primera ficha tarda.** Al arrancar, el servicio carga los 4 modelos en memoria (`GET /health` muestra el
  precalentamiento). En CPU, una ficha nueva tarda decenas de segundos y una ficha desde la caché es casi inmediata;
  las latencias medidas están en `evaluacion/resultados/`.

## Estructura

```
servicio/            API y lógica en capas (C1–C7, T1, T2), scripts, evaluación y pruebas
web/                 aplicación web estática (nginx) que solo consume /api/*
evaluacion/          conjuntos de prueba, resultados, gráficas y plantillas de revisión manual
docs/                especificaciones, ADR, diagramas, informe y presentación
```

El estado del proyecto y la evidencia de cada hito están en [`PROGRESO.md`](PROGRESO.md).
