# Ejecución completa: preparación, calibración y evaluación

Esta guía reproduce **todo** el pipeline en una máquina nueva: datos, índice, calibración de umbrales, aceptación con
los modelos reales, evaluación completa (R3 y R9) y la demo sin red. Todos los comandos se ejecutan desde la raíz del
repositorio y corren dentro de contenedores: el equipo solo necesita Docker.

> **Estado al 2026-11-08.** El código, las pruebas automáticas, los diagramas y los ADR están completos. La
> evaluación con los modelos reales (≈ 20 h de CPU en el equipo de desarrollo; ver la estimación abajo) **no se ha
> ejecutado** y se hará en un equipo más potente. Hasta entonces, las cifras de evaluación del informe y de los ADR
> «Propuesta» aparecen como *pendiente*. Ninguna cifra se escribe a mano: todas salen de `evaluacion/resultados/`.

## 0. Requisitos

- Docker (Docker Desktop en Windows o macOS) con **8 GB o más** de memoria para Docker. Los límites de los cuatro
  contenedores suman 7.0625 GiB (ADR-12).
- Solo CPU: el compose no reserva GPU. Una CPU con más núcleos acorta la evaluación.
- Internet **solo** para los pasos 1 y 2. Desde el paso 3 todo funciona sin red.
- Si el equipo ya tiene un Ollama nativo en el puerto 11434, crea un `.env` con `OLLAMA_PUERTO_HOST=11435`.

## 1. Modelos y verificación del equipo (con internet)

```bash
docker compose --profile preparacion run --rm modelos
docker compose run --rm -e FOTOTECA_H0_JSON=/app/evaluacion_datos/resultados/h0_equipo2.json servicio python -m scripts.verificar_h0
```

`verificar_h0` mide en ESTE equipo la latencia y la memoria de los cuatro modelos. La variable `FOTOTECA_H0_JSON`
evita sobrescribir `h0.json`, que es la evidencia de los ADR-10 a ADR-12 medida en el equipo de desarrollo. Con
`h0_equipo2.json` puedes recalcular la estimación de la sección 7 para este equipo.

## 2. Datos y corpus (con internet; reanudables)

```bash
docker compose run --rm servicio python -m scripts.preparar_datos
docker compose run --rm servicio python -m scripts.preparar_corpus
```

- `preparar_datos` descarga Crossmodal-3600 y las etiquetas de Open Images, y audita el EXIF. Después calcula los
  embeddings de imagen de las 3,600 fotos, que es la parte larga y se reanuda donde se quedó. Si
  `evaluacion/conjuntos/particiones.json` y los conjuntos sintéticos ya están versionados, **los reutiliza** (no los
  regenera) y solo materializa sus imágenes. Así la evaluación usa exactamente los mismos conjuntos en cualquier
  equipo.
- `preparar_corpus` construye el corpus normativo (IPTC, W3C WAI, WCAG, DCMI) y el Tesauro UNESCO.
- Evidencia: `evaluacion/resultados/datos.json` (tamaños, manifiestos con SHA-256, peso de `data/`) y
  `evaluacion/resultados/corpus_r1.json` (R1).

## 3. Índice del archivo y su verificación (sin red desde aquí)

```bash
docker compose run --rm servicio python -m scripts.indexar_archivo
docker compose run --rm servicio python -m scripts.verificar_h3
```

`indexar_archivo` reconstruye **desde cero** las colecciones, el archivo de 2,600 fotos con sus fichas iniciales
(escritas por humanos, sin modelos de lenguaje) y la caché. Además calibra τ_tesauro con el proxy léxico
(`calibracion_tesauro.json`). `verificar_h3` comprueba el número de puntos por colección, que el GPS desaparezca de la
foto guardada y de su miniatura, y que `DELETE` borre los vectores (`h3_verificacion.json`).

## 4. Calibración inicial y su aplicación

```bash
docker compose run --rm servicio python -m scripts.calibrar h4
docker compose run --rm servicio python -m scripts.calibrar h5
docker compose run --rm servicio python -m scripts.aplicar_calibracion
```

- `calibrar h4` calcula τ_ret, τ_consenso, τ_busqueda, τ_apego_visual y τ_consistencia. Usa solo `nuevas` sin
  `eval_fichas` y el archivo.
- `calibrar h5` calcula τ_fuera_dominio, τ_texto_visible y τ_inyeccion. Usa solo los conjuntos `calibracion_*`, así que
  la evaluación de los guardrails queda fuera de muestra.
- `aplicar_calibracion` escribe `servicio/config/calibracion.yaml`. El servicio lo mezcla sobre `parametros.yaml`: no
  se edita nada a mano y cada valor guarda su archivo de origen. Cambia la versión de configuración, por lo que la
  caché anterior deja de servir.

## 5. Aceptación con los modelos reales y pruebas

```bash
docker compose run --rm servicio python -m scripts.verificar_h4
docker compose run --rm servicio pytest -q
docker compose up -d
docker compose -f docker-compose.yml -f docker-compose.e2e.yml --profile pruebas build e2e
docker compose -f docker-compose.yml -f docker-compose.e2e.yml --profile pruebas run --rm e2e
```

- `verificar_h4` cataloga 10 fotos de `nuevas` por las dos rutas, busca un caso del ciclo de agente en
  `regiones_excluidas` y prueba la búsqueda simple y la compleja. Escribe `h4_aceptacion.json` y elimina sus fotos al
  terminar. Las fotos que reserva para H7 no se tocan.
- `pytest` corre ahora también las pruebas que usan los conjuntos de `evaluacion/conjuntos/`.
- El E2E con Playwright recorre la web. Construir la imagen necesita internet.
- Opcional: `python -m scripts.ajustar_prompts --etiqueta v1` muestra las fichas de las 10 fotos de `ajuste_prompts`,
  para revisar la redacción de los prompts.

## 6. Evaluación completa (R3 y R9), en dos pasadas

Cada módulo guarda caso por caso en `evaluacion/resultados/casos/`. Si algo se interrumpe, al repetir el comando se
reanuda donde se quedó. Conviene probar primero con `--rapido` (una cuarta parte de cada conjunto):

```bash
docker compose run --rm servicio python -m evaluacion.ejecutar_todo --rapido
```

**Antes de la corrida completa, deshaz la prueba rápida.** La corrida completa reutilizaría los casos de la rápida, que
toma la misma cuarta parte de cada conjunto y los generó con los umbrales previos. Además, `aprendizaje` valida fichas
y cambia el archivo.

1. Mueve o borra `evaluacion/resultados/casos/` y los `evaluacion/resultados/<modulo>.json` que generó la prueba.
2. Reconstruye el archivo con `python -m scripts.indexar_archivo`. Borra fichas, subidas y caché, pero conserva
   `config/calibracion.yaml`.

**Corrida parcial (`--fraccion`).** Si no hay tiempo para la corrida completa, `--fraccion 0.5` evalúa la mitad de
cada conjunto: toma el inicio de la misma muestra con semilla fija, así que una corrida posterior con una fracción
mayor (o sin `--fraccion`) reutiliza los casos ya calculados y solo agrega los que faltan. La excepción es
`aprendizaje`, cuya curva depende del tamaño de los bloques: guarda los casos de cada fracción aparte. Cada
`<modulo>.json` registra su `fraccion`. Ejemplo: agrega `--fraccion 0.5` a los dos comandos de abajo.

**Pasada 1: generaciones de referencia y calibración final.**

```bash
docker compose run --rm servicio python -m evaluacion.ejecutar_todo --solo r3_embeddings,r3_modelos,rag_fichas,enrutador,cache
docker compose run --rm servicio python -m scripts.aplicar_calibracion
```

Después de la pasada 1, `aplicar_calibracion` incorpora τ_dup (barrido de `cache`, ADR-04) y τ_consenso y τ_acuerdo
(validación cruzada de `enrutador`, ADR-03).

**Pasada 2: el resto, con la configuración final.**

```bash
docker compose run --rm servicio python -m evaluacion.ejecutar_todo --solo agente,guardrails,inyeccion_consultas_cortas,aprendizaje,desempeno,analizar_revision_manual,resumen
```

`aprendizaje` corre después de `enrutador` porque valida fotos de la galería. Al terminar, `resumen` escribe
`evaluacion/resultados/RESUMEN.md` con cada cifra y su archivo de origen.

## 7. Estimación de tiempo (no es un resultado)

La estimación se calcula como **número de llamadas a modelos × p50 medido en H0** en el equipo de desarrollo (CPU Apple
arm64, 8 vCPU; `evaluacion/resultados/h0.json` → `verificaciones.0.6`):

- embedding de imagen: 2.464 s;
- P1 a 512 px: 34.28 s;
- P3 con LFM3: 39.351 s;
- P3 con Qwen: 35.583 s;
- ruta completa ≈ P1 + P3 = 73.6 s.

P2, P4 y el juez P7 no se midieron en H0. P2 se aproxima con P1, porque los dos envían la imagen a Qwen; P4 y P7 no
entran en la cuenta.

| Paso | Llamadas principales | Estimación en el equipo de desarrollo |
|---|---|---|
| Embeddings de las 3,600 fotos | 3,600 × 2.464 s | ≈ 2.5 h |
| `r3_embeddings` (pipeline) | 500 descripciones P1 × 34.28 s (con 1,000 pasaría de 3 h, así que se usan 500) | ≈ 4.8 h |
| `r3_modelos` | 60 × (P1 + P2 + P3 Qwen + P3 LFM3) = 60 × 143.5 s | ≈ 2.4 h + juez |
| `rag_fichas` | 120 fichas completas × 73.6 s | ≈ 2.5 h + juez |
| `enrutador` | reutiliza las fichas de `r3_modelos`; sube la galería (1,000 × 2.464 s) y hace 40 búsquedas | ≈ 0.7 h + P4 |
| `agente` | 50 fotos × 2 configuraciones × 73.6 s | ≈ 2.0 h |
| `guardrails` | ≈ 50 fichas × 73.6 s | ≈ 1.0 h |
| `cache` | ≈ 50 fichas × 73.6 s + 300 embeddings | ≈ 1.2 h |
| `aprendizaje` | 100 fichas × 73.6 s | ≈ 2.0 h |
| **Total** | | **≈ 19 h más el juez y P4** |

En un equipo más potente, recalcula con su propio `h0_equipo2.json` (paso 1). Las latencias que reporta H7 son las de
ESE equipo, porque cada JSON registra su hardware. La de la laptop de la demo se mide aparte (acción del autor).

## 8. Demo sin red (H9)

```bash
docker compose run --rm servicio python -m scripts.preparar_demo
docker compose -f docker-compose.yml -f docker-compose.sinred.yml up -d
docker compose -f docker-compose.yml -f docker-compose.sinred.yml run --rm servicio python -m scripts.demo_sin_red
docker compose run --rm servicio python -m scripts.verificar_contratos
```

- `preparar_demo` crea las cinco fotos del guion en `data/demo/`.
- `demo_sin_red` comprueba que no haya salida a internet y ejecuta los 9 pasos del guion contra la API a través de
  nginx (`demo_sin_red.json`). Mide la memoria con `docker stats` en otra terminal mientras corre.
- `verificar_contratos` deja la evidencia del contrato de capas (`contrato_capas.json`, ADR-13).

## 9. Preparar el equipo de la demostración

`data/` y los volúmenes de Docker no se versionan, así que el equipo de la demo debe prepararse con internet **antes**
del día de la presentación. Los embeddings de las fotos son el paso más largo.

1. Clona el repositorio y ejecuta los pasos 1 a 3 de esta guía: modelos, datos, corpus e índice. `preparar_datos`
   reutiliza los conjuntos versionados.
2. Umbrales:
   - Si `servicio/config/calibracion.yaml` ya está versionado (lo deja la evaluación del paso 6), no hace falta
     recalibrar.
   - Si no está, ejecuta el paso 4. Los pasos 4 y 5 de la demo (bloqueo de una captura y ciclo de agente) dependen de
     esos umbrales.
3. `python -m scripts.preparar_demo` y un ensayo completo sin red (paso 8). En ese equipo también se miden la latencia
   y la memoria reales de la demo.
4. Opcional, para ahorrar tiempo: copia de un equipo ya preparado la carpeta `data/` y los volúmenes `ollama_modelos`,
   `qdrant_datos` y `sqlite_datos` (por ejemplo, con `docker run --rm -v <volumen>:/v -v "$PWD:/r" alpine tar czf
   /r/<volumen>.tgz -C /v .`, y lo inverso para restaurar).
5. Si el equipo ya estaba preparado y el repositorio cambió, `git pull` y luego `docker compose up -d --build`. El
   código y los umbrales calibrados (`servicio/config/calibracion.yaml`) van dentro de la imagen del servicio, así que
   hay que reconstruirla; la web se actualiza sola porque `web/` va montada. Hazlo con internet: si cambió
   `requirements.txt`, la reconstrucción descarga paquetes. Después, espera a que `/health` diga «ok» con los modelos
   precalentados y repite el ensayo sin red.

## 10. Después de la evaluación

1. Revisa `evaluacion/resultados/RESUMEN.md`.
2. Pasa a «Aceptada» los ADR que estaban como «Propuesta», con las cifras y la ruta de su archivo de resultados.
3. Completa las cifras «pendiente» del informe con los valores de los JSON. Cada número debe existir tal cual en
   `evaluacion/resultados/`.
4. Llena las plantillas de `evaluacion/revision_manual/` (revisión humana) y corre
   `python -m evaluacion.analizar_revision_manual`.
5. Versiona `evaluacion/resultados/`, `evaluacion/graficas/`, `evaluacion/revision_manual/` y
   `servicio/config/calibracion.yaml`. `data/` no se versiona.

## Si algo falla

- **Tiempo agotado en un lote de embeddings:** los scripts por lotes esperan hasta 30 s por imagen y reintentan el
  lote; vuelve a lanzar el comando y se reanuda.
- **El contenedor `ollama` se acerca a su límite de 5 GiB** (`docker stats`): reinícialo con
  `docker compose restart ollama`. Los modelos se recargan y los procesos se reanudan al relanzarlos (ADR-12).
- **Error 503 durante la evaluación:** el módulo comprueba la infraestructura y repite una vez. Si persiste, revisa
  `GET /health` y relanza el módulo, que continúa donde se quedó.
