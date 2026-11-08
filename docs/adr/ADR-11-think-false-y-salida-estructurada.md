# ADR-11: Razonamiento desactivado, salida estructurada con JSON Schema y muestreo por modelo

**Estado:** Aceptada
**Fecha:** 2026-11-07
**Atributos de calidad en juego:** latencia, confiabilidad del formato (JSON válido), calidad de la ficha

## Contexto
Los modelos compactos (Qwen3.5-0.8B y LFM3-1.7B) tienen modo de razonamiento («thinking») y traen sus propios
valores de muestreo (Qwen: `temperature` 1 y `presence_penalty` 1.5). El servicio necesita respuestas **cortas,
deterministas y en JSON válido** para armar la ficha, en CPU, donde cada token cuenta.

## Decisión
1. `think: false` en **todas** las llamadas (el adaptador además elimina cualquier bloque `<think>…</think>`).
2. La salida se fuerza con el parámetro `format` de `/api/chat` usando el **JSON Schema** de cada prompt (P1–P7).
3. El muestreo se envía siempre explícito: `temperature` 0.2 para fichas y 0 para clasificaciones y jueces,
   `top_p` 0.9, `num_ctx` 4096. Por modelo: Qwen conserva su `presence_penalty` de **1.5** y se ejecuta **sin
   decodificación especulativa** (`draft_num_predict: 0`); LFM3 usa `presence_penalty` 0.
4. P1 se acota (versión 2): descripción de 2–3 oraciones, hasta 8 elementos y `texto_visible` solo con texto real.

## Alternativas
- **Dejar el razonamiento activo:** multiplica los tokens generados sin mejorar un JSON corto; ver evidencia.
- **Sin `format` (solo pedir JSON en el prompt):** más rápido pero el JSON deja de ser válido.
- **`presence_penalty` 0 en Qwen:** repetición degenerada en las listas y JSON truncado.
- **Mantener el draft de Qwen (decodificación especulativa):** en esta CPU genera menos tokens por segundo.
- **Subir `num_predict` de P1 a 500:** la salida se alarga y vuelve la repetición; no mejora la validez.

## Evidencia
Fuente: `evaluacion/resultados/h0.json`.

| Prueba (P1 de Qwen salvo indicación) | Configuración | JSON válidos | Observación |
|---|---|---|---|
| `0.2_corrida1` | `presence_penalty` 0, P1 v1 | 3/5 | 2 truncados por `num_predict` (repetición en listas) |
| `0.6b` | `presence_penalty` 0 | 2/4 | repetición media en listas 0.182 |
| `0.6b` | `presence_penalty` 1.5 | 4/4 | repetición 0 |
| `0.6b` | `presence_penalty` 1.5, sin `format` | **0/4** | sin esquema no hay JSON válido |
| `0.6b` | `presence_penalty` 1.5, `num_predict` 500 | 4/4 | más tokens (p50 272) y repetición 0.263 |
| `0.2_corrida3` | `presence_penalty` 1.5, draft activo, P1 v1 | 4/5 | una foto rebasó el tope |
| `0.2` (final) | `presence_penalty` 1.5, sin draft, **P1 v2** | **5/5** | 137–184 tokens; `texto_visible` vacío en las 5 |

**Draft (decodificación especulativa).** La latencia total de 0.6b está sesgada por la caché de prompt de Ollama
(las configuraciones que repitieron el prompt anterior tuvieron un prefill de ~0.25 s en lugar de ~23 s;
`0.6b.analisis.cache_de_prompt`). Por eso se compara la **velocidad de generación**
(`0.6b.analisis.tokens_por_s_generacion`): 6.07 tokens/s con draft contra **11.55 tokens/s sin draft**.

**Razonamiento y formato** (`0.6.adr11_think_y_format`, corrida 5: las mismas 3 fotos en cada configuración; P1 a
768 px; con razonamiento se sube `num_predict` a 1024 para que tenga espacio):

| Llamada | Configuración | Latencia p50 (s) | JSON válidos | Respuestas con razonamiento |
|---|---|---|---|---|
| P1 · Qwen | `think: true` | 66.206 | 2/3 | 3/3 |
| P1 · Qwen | **`think: false`** | **41.893** | **3/3** | 0/3 |
| P3 · LFM3 | `think: true` | 107.411 | **0/3** | 3/3 |
| P3 · LFM3 | **`think: false`** | **51.896** | **3/3** | 0/3 |
| P3 · LFM3 | `think: false`, **sin `format`** | 29.9 | **0/3** | — |

Con razonamiento, la latencia sube 58 % en P1 y 107 % en P3 (p50), y LFM3 agota los 1024 tokens pensando sin
entregar un JSON válido. Sin `format`, P3 es más rápido pero ninguna respuesta es un JSON válido. Con la
configuración elegida, P3 de LFM3 dio **8/8** JSON válidos sobre 8 fotos (p50 39.351 s, p95 59.444 s; mediana de
263 tokens de salida; `0.6.p3_lfm3`).

## Consecuencias
- **Se gana:** JSON válido y descripciones más cortas (menos tokens = menos latencia en CPU).
- **Se sacrifica:** descripciones de P1 menos detalladas; la riqueza de la ficha la aporta la composición (P3) con
  el contexto recuperado.
- **Riesgos:** la gramática del JSON Schema puede recortar cadenas largas (`maxLength`); el guardrail de reglas
  IPTC y la verificación de esquema lo vigilan. Los valores de muestreo deben revisarse si cambia la versión de
  Ollama o de los modelos.
