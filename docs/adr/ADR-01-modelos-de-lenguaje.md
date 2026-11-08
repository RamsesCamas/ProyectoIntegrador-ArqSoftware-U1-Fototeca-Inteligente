# ADR-01: Selección de los modelos de lenguaje: Qwen3.5-0.8B para la visión y la ruta rápida, LFM3-1.7B para la composición

**Estado:** Propuesta
**Fecha:** 2026-11-08
**Atributos de calidad en juego:** calidad de la ficha (fidelidad y relevancia), latencia en CPU, memoria (límite de 5g
del contenedor `ollama`), validez del JSON, idioma español, licencia

## Contexto
Fototeca Viva tiene que hacer dos cosas distintas con modelos de lenguaje: **ver** la foto y describirla de forma
objetiva, y **componer** una ficha IPTC en español con la fuente de cada campo a partir de esa descripción y del
contexto recuperado (fichas vecinas, reglas y términos del tesauro). Todo corre en CPU, en una laptop con unos 8 GB
para Docker y con los cuatro modelos del sistema cargados a la vez dentro del límite de 5g del contenedor `ollama`
(ADR-12). El curso pide comparar al menos dos modelos de lenguaje con evidencia medida, y el resultado alimenta al
enrutador (ADR-03): una ruta rápida y barata y otra más capaz y costosa.

## Decisión
- **`qwen3.5:0.8b`** (visión nativa) es «los ojos» y la ruta rápida: P1 (describir la imagen), P2 (ficha rápida con la
  imagen y las fichas vecinas) y P6 (verificar atributos sensibles). También es el **respaldo** de P3, P4 y P5 en el
  gateway.
- **`lfm3:1.7b-q4_K_M`** (solo texto) es «el catalogador»: P3 (ficha completa a partir de la descripción de P1 y del
  contexto), P4 (descomponer búsquedas), P5 (reformular búsquedas) y P7 (juez, solo en la evaluación).
- Las dos se llaman con `think: false` y con el JSON Schema de cada prompt en `format` (ADR-11). La asignación vive en
  el encabezado de cada `servicio/fototeca/modelos/prompts/Pn_*.md` (`modelo_preferido` y `modelo_respaldo`).

## Alternativas
- **Un solo modelo (Qwen3.5-0.8B) para todo:** menos memoria y una sola ruta, pero la composición con contexto largo
  quedaría en el modelo más pequeño. Es justo una de las configuraciones del experimento (`qwen_composicion`); si
  rindiera igual que LFM3, este ADR se reemplaza.
- **Solo LFM3:** no es posible, porque no acepta imágenes; haría falta otro modelo de visión.
- **Modelos más grandes** (por ejemplo, una variante de 2B o un modelo de visión de 3B o más): con los cuatro modelos
  actuales el contenedor `ollama` ya llegó a un pico de 4.592 GiB con un límite de 5.0 GiB (evidencia abajo), así que
  no queda margen para uno mayor sin romper el presupuesto de memoria.
- **APIs de modelos en la nube:** descartadas por la regla de ejecución local (R2).

## Evidencia
**pendiente:** experimento R3 de modelos de lenguaje sobre las 60 fotos de `eval_fichas`, con tres configuraciones:
`qwen_rapida` (P2 con imagen y vecinos), `qwen_composicion` y `lfm3_composicion` (P3 con la **misma** descripción P1,
calculada una sola vez). Métricas: fidelidad y relevancia de 0 a 5 con el juez P7, similitud con granite contra las
descripciones humanas, chrF, porcentaje de JSON válido a la primera, porcentaje que pasa los guardrails de salida,
latencia p50 y p95, RAM con el modelo cargado, tamaño en disco, cuantización y licencia. Saldrá en
`evaluacion/resultados/r3_modelos.json` (caso por caso en `r3_modelos_detalle.csv`), con la tabla comparativa y la
conclusión de qué modelo va en cada ruta.

**Datos de viabilidad ya medidos** (no sustituyen al experimento: muestras pequeñas y sin calificar la calidad).
Fuente: `evaluacion/resultados/h0.json` y `evaluacion/resultados/h0_memoria_por_modelo.txt`.

| Medición | Qwen3.5-0.8B | LFM3-1.7B | Fuente |
|---|---|---|---|
| P1 con imagen a 512 px: JSON válidos, p50 y p95 | 8/8 · 34.28 s · 38.499 s | — | `verificaciones.0.6.p1_por_lado.512` |
| P3 (ficha completa, hasta 600 tokens): JSON válidos, p50 y p95 | 5/5 · 35.583 s · 42.178 s (solo texto, como respaldo) | 8/8 · 39.351 s · 59.444 s | `verificaciones.0.6.p3_qwen_texto` y `verificaciones.0.6.p3_lfm3` |
| Tamaño en disco (bytes) | 1322069277 | 1099638680 | `modelos_descargados` |
| Memoria residente del proceso `llama-server` (VmRSS) | 1617684 kB | 1438764 kB | `h0_memoria_por_modelo.txt` |

- Con los cuatro modelos cargados y fichas en curso, el pico del contenedor `ollama` fue de 4.592 GiB con un límite de
  5.0 GiB (`h0.json` → `verificaciones.0.5.docker_stats.pico_por_contenedor_gib` y `limite_por_contenedor_gib`; ADR-12).
- Hardware de esas mediciones: VM de Docker con CPU Apple `aarch64` de 8 núcleos (`h0.json` → `hardware_contenedor`).
  La demo será en una laptop Windows x86, donde la latencia se medirá de nuevo.

## Consecuencias
- **Se gana:** visión nativa en un modelo de menos de mil millones de parámetros y un compositor de texto más capaz,
  ambos dentro del límite de memoria; el gateway tiene un respaldo real para las tareas de texto.
- **Se sacrifica:** la ruta completa encadena dos llamadas a modelos (P1 y luego P3), cada una de decenas de segundos en
  CPU según H0. Por eso el enrutador manda a la ruta rápida las fotos cuyos vecinos coinciden (ADR-03), y los lotes
  corren en segundo plano (ADR-08).
- **Por qué el compromiso es adecuado para el dominio y el equipo:** catalogar no es una tarea de tiempo real; el
  archivista revisa y valida cada ficha antes de publicarla, y la calidad de modelos tan pequeños se compensa con el
  RAG (ejemplos y normas), los guardrails de salida y la revisión humana. Ningún modelo mayor cabe en la laptop junto
  con los otros tres.
- **Riesgos:** con tan pocos parámetros, las fichas pueden omitir detalles o inventarlos (alucinación); el juez P7 es
  también un modelo pequeño, así que su calificación se contrasta con métricas sin juez y con una revisión manual. La
  licencia LFM Open License v1.0 está pendiente de revisión por el autor para el uso académico previsto.
