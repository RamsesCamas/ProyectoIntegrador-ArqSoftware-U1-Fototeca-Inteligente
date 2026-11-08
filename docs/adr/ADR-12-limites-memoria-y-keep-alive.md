# ADR-12: Límites de memoria por contenedor, modelos siempre cargados y caché de prompts desactivada

**Estado:** Aceptada
**Fecha:** 2026-11-08
**Atributos de calidad en juego:** memoria (presupuesto de 7.1 GB), disponibilidad durante la demo, latencia
predecible, veracidad de las mediciones

## Contexto
La demo corre en una laptop con Docker Desktop (unos 8 GB para Docker) y debe servir **cuatro modelos a la vez**
en CPU: Qwen3.5-0.8B (visión), LFM3-1.7B (composición), EmbeddingGemma-2 440m (imagen y texto) y granite (texto).
El presupuesto de diseño reparte la memoria así: `ollama` 5g, `qdrant` 512m, `servicio` 1536m y `web` 64m, y lo
resume como «≈ 7.1 GB».
Recargar un modelo en CPU cuesta segundos en cada petición. Un proceso de modelo que muere a media ficha deja la
petición en error 500.

## Decisión
1. Se respetan esos límites tal cual: **5g + 512m + 1536m + 64m** (suma de 7.0625 GiB). El «7.1 GB» del presupuesto
   se interpreta en las unidades binarias que usa Docker.
2. `OLLAMA_KEEP_ALIVE=-1` y `OLLAMA_MAX_LOADED_MODELS=4`: los cuatro modelos se quedan cargados.
   `OLLAMA_NUM_PARALLEL=1` y `OLLAMA_CONTEXT_LENGTH=4096`.
3. **Se desactiva la caché de prompts en RAM de llama-server** con `LLAMA_ARG_CACHE_RAM=0` en el contenedor
   `ollama`. Se conserva la reutilización del prefijo dentro de cada slot.
4. `OLLAMA_NO_CLOUD=1`: no hay funciones en la nube (R2).

## Alternativas
- **Dejar la caché de prompts con su valor por defecto:** descartado. Ollama 0.40.15 lanza un `llama-server` por
  modelo sin `--cache-ram`, y cada uno guarda hasta 8192 MiB de estados de prompt. En H0 el contenedor llegó a su
  límite y el kernel mató el proceso de Qwen (evidencia abajo).
- **Limitar la caché a un tamaño pequeño en lugar de desactivarla:** solo ayudaría cuando se repite exactamente el
  mismo prompt con la misma imagen. Ese caso ya lo resuelve la caché de fichas de la aplicación (C4), que es medible
  e invalidable (ADR-04). Además, la caché de llama.cpp sesgó las mediciones de H0: 0.6b y P1 a 1024 px.
- **Subir el límite de `ollama` a 6g:** rompe el presupuesto de 7.1 GB y no corrige la causa; la caché
  seguiría creciendo.
- **`keep_alive` corto para granite o `num_ctx` 3072 para LFM3** (las mitigaciones previstas para el riesgo de
  memoria): innecesarias después de desactivar la caché (ver el uso medido).
- **`OLLAMA_KEEP_ALIVE` por defecto (5 min):** la primera ficha después de 5 minutos sin uso pagaría la carga de
  cada modelo. Por ejemplo, LFM3 tarda 3.349 s en cargar (`h0.json` → `0.1.carga_s`), y el tiempo se multiplica por
  cuatro modelos en plena demo.

## Evidencia
Fuente: `evaluacion/resultados/h0.json` (verificaciones `0.5`, `0.5_sin_limite_cache` y `0.6_corrida4`), más
`h0_cgroup_ollama_antes.txt`, `h0_cgroup_ollama.txt`, `h0_docker_stats_antes.jsonl` y `h0_docker_stats.jsonl`.

| Medición del contenedor `ollama` | Caché de prompts por defecto (corrida 4) | `LLAMA_ARG_CACHE_RAM=0` (corrida 5) |
|---|---|---|
| Pico de uso en `docker stats` (GiB; sin la caché de archivos) | **5.0** (= límite) | **4.592** |
| Procesos de modelo terminados por el kernel (`oom_kill`) | **1** | **0** |
| ¿Algún contenedor alcanzó su límite? | sí: `ollama` | no |
| Cuatro modelos cargados a la vez (`/api/ps`) | sí | sí |
| Muestras de `docker stats` | 2,673 | 1,495 |

- Las mediciones de la corrida 5 cubren 0.6 y 0.5 completas con los cuatro modelos cargados: P1 a 512, 768 y
  1024 px, P3 con LFM3 y con Qwen, las pruebas de razonamiento de ADR-11 y tres ciclos de ficha. El pico dentro de
  la ventana de 0.5 fue de 4.565 GiB (`0.5.docker_stats`).
- `memory.peak` del cgroup llega al límite en las dos corridas (5,368,725,504 y 5,368,733,696 bytes): el kernel
  llena el resto con caché de archivos y la recupera cuando hace falta (`memory.events` → `max`). Eso es normal.
  Lo que distingue las corridas es la memoria de trabajo (`docker stats`) y `oom_kill`.
- **Memoria residente por modelo** durante la corrida 5 (`h0_memoria_por_modelo.txt`, VmRSS de cada
  `llama-server`): Qwen 1.543 GiB, LFM3 1.372 GiB, EmbeddingGemma-2 440m 0.881 GiB y granite 0.667 GiB; en total,
  4.464 GiB. Ese es el piso de memoria de tener los cuatro modelos cargados.
- La evidencia de la causa está en `h0_llama_server_cache_ram.txt`: `--cache-ram` vale 8192 MiB por defecto
  (variable `LLAMA_ARG_CACHE_RAM`), Ollama no lo fija al lanzar `llama-server` y, tras el cambio, el log dice
  `prompt cache is disabled`.
- **Latencias descartadas por la caché.** Las fotos de la muestra de 0.6 miden alrededor de 640×480
  (`0.6.p1_por_lado.768.tamanos_enviados`), así que a 768 y a 1024 px se envía la misma imagen. En la corrida 4 la
  caché de prompts respondió esas peticiones repetidas sin recalcular la imagen: P1 tuvo una p50 de 16.988 s a 1024 px
  contra 42.698 s a 768 px (`0.6_corrida4.p1_por_lado_segun_log`). Esas latencias se descartaron
  (`0.6_corrida4.nota`) y 0.6 se repitió completa con la caché desactivada (corrida 5).
- Suma de límites: 5,120 + 512 + 1,536 + 64 MiB = 7,232 MiB = **7.0625 GiB** (Docker usa unidades binarias).
  El uso de los cuatro contenedores juntos durante la demo se mide en H9.

## Consecuencias
- **Se gana:** los cuatro modelos caben con margen en el límite de 5g sin cambiar ningún modelo, y las latencias
  medidas (H0 y H7) ya no se benefician de peticiones repetidas.
- **Se sacrifica:** una petición idéntica a otra anterior vuelve a pagar el *prefill* completo. La caché de fichas
  de la aplicación cubre ese caso con reglas explícitas (ADR-04).
- **Riesgos:** si la versión de Ollama cambia, la variable `LLAMA_ARG_CACHE_RAM` podría dejar de aplicarse; el log
  de `ollama` debe decir `prompt cache is disabled`. Esto se comprueba en H9 con `docker stats`.
