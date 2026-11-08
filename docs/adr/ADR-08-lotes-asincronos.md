# ADR-08: Lotes asíncronos con un solo trabajador, sin Celery ni Redis

**Estado:** Propuesta
**Fecha:** 2026-11-08
**Atributos de calidad en juego:** latencia percibida por el archivista, memoria (presupuesto de los contenedores),
simplicidad de operación sin red, recuperación ante reinicios

## Contexto
El archivista recibe lotes de fotos de un evento y quiere catalogarlos de una vez. Cada ficha nueva tarda decenas de
segundos en CPU (ADR-01), así que una petición HTTP que espere un lote completo agotaría los tiempos de espera del
navegador y del proxy. El servidor de modelos atiende una petición a la vez (`OLLAMA_NUM_PARALLEL=1`, ADR-12) y la
memoria de los contenedores tiene un presupuesto fijo.

## Decisión
- `POST /lotes` recibe los ids de fotos ya cargadas y responde **202** con un `lote_id`; `GET /lotes/{id}` devuelve el
  progreso (`total`, `completadas`, `fallidas`, `en_proceso`) y las fichas listas. La web consulta el progreso cada pocos
  segundos y lo anuncia en una región `aria-live`.
- `GestorLotes` (`servicio/fototeca/orquestacion/lotes.py`) usa un `ThreadPoolExecutor` de **un solo trabajador**: una
  ficha a la vez, en coherencia con `OLLAMA_NUM_PARALLEL=1`.
- El estado vive en SQLite (`AlmacenLotes`, adaptador `LotesSqlite`), así que un lote interrumpido por un reinicio se
  reanuda al arrancar el servicio.
- Cada foto del lote tiene su propio `traza_id`; un error en una foto la marca como fallida y no detiene el resto.
- La catalogación de **una sola** foto sigue siendo síncrona (`POST /fichas`), porque el archivista quiere ver esa ficha
  al momento.

## Alternativas
- **Celery con Redis o RabbitMQ:** uno o dos contenedores más, con su memoria, su configuración y sus puntos de falla,
  para una cola que en esta máquina tiene un solo consumidor útil.
- **Varios trabajadores:** competirían por la misma CPU, y Ollama atendería sus llamadas una por una de todas formas.
- **Procesar el lote dentro de la petición HTTP:** el navegador y el proxy cortarían la conexión (nginx espera hasta
  300 s, `web/nginx.conf`).
- **Tareas en segundo plano de FastAPI sin estado persistente:** un reinicio perdería el progreso del lote.

## Evidencia
**pendiente:**
- latencia de punta a punta y por capa de las fichas (p50 y p95, por ruta) a partir de las trazas, en
  `evaluacion/resultados/desempeno.json`, para dimensionar cuánto tarda un lote;
- memoria de los cuatro contenedores durante el guion de la demo con `docker stats` (verificación final sin red).

Contexto de memoria ya medido: con los cuatro modelos cargados y fichas en curso, el pico del contenedor `ollama` fue de
4.592 GiB con un límite de 5.0 GiB y la suma de picos de los contenedores en la ventana de medición fue de 4.813 GiB
(`evaluacion/resultados/h0.json` → `verificaciones.0.5.docker_stats`). No hay margen razonable para sumar un broker y
sus trabajadores dentro del presupuesto (ADR-12).

## Consecuencias
- **Se gana:** cero contenedores y cero dependencias extra; la operación sin red sigue siendo `docker compose up -d`; el
  progreso sobrevive a un reinicio.
- **Se sacrifica:** el rendimiento queda limitado a una ficha a la vez, y una ficha síncrona que llegue durante un lote
  espera su turno en Ollama.
- **Riesgos:** el diseño supone un solo proceso del servicio (uvicorn sin varios workers); con varios procesos habría
  que coordinar quién toma cada lote.
