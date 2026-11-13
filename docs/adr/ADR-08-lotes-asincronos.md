# ADR-08: Lotes asíncronos con un solo trabajador, sin Celery ni Redis

**Estado:** Aceptada
**Fecha:** 2026-11-08 (evidencia: 2026-11-13)
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
- **Cuánto tarda un lote** (`evaluacion/resultados/desempeno.json` → `metricas.por_ruta.fichas`, configuración
  vigente). Una ficha tarda en la p50 25.996 s por la ruta rápida (70 fichas) y 56.793 s por la completa (95). Con el
  enrutador calibrado, el 0.8667 de las fotos va a la rápida (`enrutador.json`), así que un lote de 20 fotos ocupa unos 10
  minutos con un solo trabajador (estimación con esas p50: 20 × (0.8667 × 25.996 + 0.1333 × 56.793) s; no es una
  medición de un lote). Es aceptable para un archivo que se cataloga en segundo plano.
- **Memoria durante la demo sin red** (`evaluacion/resultados/h9_memoria.json`): la suma de picos fue de 4.962 GiB,
  contra 7.0625 GiB de límites; `ollama` llegó a 4.429 de 5.0 GiB. Un broker y sus trabajadores tendrían que caber en
  el margen que queda, y un segundo proceso que llamara a Ollama competiría por la misma CPU, que es el cuello de
  botella (más del 90 % del tiempo de una ficha está en los modelos; Tabla 15 del informe).

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
