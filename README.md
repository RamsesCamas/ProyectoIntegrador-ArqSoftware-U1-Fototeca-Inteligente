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

## Ejemplos con curl

Con el sistema levantado (`docker compose up -d`), estos comandos usan la API a través de la web, en
`http://localhost:8080/api/...` (la documentación OpenAPI está en `http://localhost:8000/docs`). Cada comando ocupa una
sola línea y funciona igual en bash y en PowerShell:

- En **Windows PowerShell 5.1**, `curl` es un alias de `Invoke-WebRequest`: escribe `curl.exe` en lugar de `curl`. En
  PowerShell 7 y en bash no hace falta.
- Los cuerpos JSON viajan por la entrada estándar (`echo '…' | curl … -d "@-"`), para que las comillas lleguen intactas en
  los dos shells. PowerShell 5.1 convierte en «?» los acentos que pasan por la tubería: usa PowerShell 7 o escribe el
  acento como escape JSON (por ejemplo, `\u00e1` para «á»).
- Sustituye `foto.jpg`, `DOC_ID` y `TRAZA_ID`. El `documento_id` sale de la respuesta de la carga; el `traza_id`, de la
  ficha (`meta.traza_id`) o de la cabecera `X-Traza-Id`, que se ve agregando `-i` al comando.

```bash
# Estado del sistema: servicio, modelos, Qdrant, almacén y caché
curl -s http://localhost:8080/api/health

# 1. Cargar una foto (JPEG o PNG): responde 201 con su documento_id y los posibles duplicados
curl -s http://localhost:8080/api/documentos -F "archivos=@foto.jpg" -F "tipo=foto"

# 2. Catalogar la foto cargada: ficha IPTC con la fuente de cada campo y meta (ruta, modelos, caché, guardrails, traza_id)
echo '{"documento_id": "DOC_ID"}' | curl -s http://localhost:8080/api/fichas -H "Content-Type: application/json" -d "@-"

# 2b. Cargar y catalogar en una sola llamada, y consultar después la ficha guardada
curl -s http://localhost:8080/api/fichas -F "foto=@foto.jpg"
curl -s http://localhost:8080/api/fichas/DOC_ID

# 3. Buscar por texto en español: cada resultado trae sus razones
echo '{"texto": "mercado con frutas", "k": 6}' | curl -s http://localhost:8080/api/busquedas -H "Content-Type: application/json" -d "@-"

# 3b. Buscar por foto (imagen a imagen, sin modelo de lenguaje)
curl -s http://localhost:8080/api/busquedas -F "imagen=@foto.jpg" -F "k=6"

# 4. Registrar la opinión sobre una ficha y validarla con una corrección: la ficha validada se vuelve ejemplo del RAG
echo '{"traza_id": "TRAZA_ID", "util": true, "comentario": "El texto alternativo omite el toldo", "correcciones": {"texto_alternativo": "Puesto de mercado con mangos bajo un toldo azul."}, "validar_ficha": true}' | curl -s http://localhost:8080/api/retroalimentacion -H "Content-Type: application/json" -d "@-"

# 5. Consultar las métricas (latencia por capa, caché, guardrails, modelos, retroalimentación y accesibilidad del archivo)
curl -s http://localhost:8080/api/metricas
curl -s "http://localhost:8080/api/metricas?desde=2026-11-08T00:00:00Z"
```

Los errores tienen la forma `{"error": {"codigo", "mensaje", "traza_id"}}`; una entrada bloqueada por los guardrails
responde 422 con un `mensaje_seguro`.

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
