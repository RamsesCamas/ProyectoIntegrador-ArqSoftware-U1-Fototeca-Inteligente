# ADR-01: Selección de los modelos de lenguaje: Qwen3.5-0.8B ve y compone las fichas; LFM3-1.7B interpreta las búsquedas y es el respaldo

**Estado:** Aceptada
**Fecha:** 2026-11-08 (evidencia de R3 y decisión final: 2026-11-13)
**Atributos de calidad en juego:** calidad de la ficha (fidelidad, relevancia y fuentes verificables), latencia en CPU,
memoria (límite de 5g del contenedor `ollama`), validez del JSON, idioma español, licencia

## Contexto
Fototeca Viva usa modelos de lenguaje para dos trabajos distintos. Primero, **ver** la foto y describirla de forma
objetiva. Después, **componer** una ficha IPTC en español que diga la fuente de cada campo. La composición parte de
esa descripción y del contexto recuperado: fichas vecinas, reglas y términos del tesauro. Además, una búsqueda compleja
se **interpreta** antes de ir a la base vectorial. Todo corre en CPU, en una laptop con unos 8 GB para Docker, con los
cuatro modelos del sistema cargados a la vez dentro del límite de 5g del contenedor `ollama` (ADR-12). El curso pide
comparar al menos dos modelos de lenguaje con evidencia medida. El resultado alimenta al enrutador (ADR-03), que elige
entre una ruta rápida y barata y otra más capaz y costosa.

La hipótesis inicial era que LFM3, con más del doble de parámetros, compondría mejor que Qwen. El experimento R3 la
puso a prueba con una regla de decisión escrita antes de ver los resultados, y el resultado la refutó.

## Decisión
- **`qwen3.5:0.8b`** (visión nativa) **ve y compone**:
  - P1: describir la imagen;
  - P2: la ficha rápida, con la imagen y las fichas vecinas;
  - P3: la ficha completa, desde la descripción de P1 y el contexto;
  - P6: verificar atributos sensibles.
  - También es el respaldo de P4 y P5.
- **`lfm3:1.7b-q4_K_M`** (solo texto) **interpreta las búsquedas y respalda**:
  - P4: descomponer búsquedas;
  - P5: reformularlas;
  - el **respaldo de P3** en el gateway;
  - P7: el juez, solo en la evaluación.
- Los dos se llaman con `think: false` y con el JSON Schema de cada prompt en `format` (ADR-11). La asignación vive en
  el encabezado de cada `servicio/fototeca/modelos/prompts/Pn_*.md` (`modelo_preferido` y `modelo_respaldo`).
- No se reemplaza ningún modelo: los cuatro siguen cargados, y cambia solo cuál de los dos de lenguaje compone P3.

## Alternativas
- **LFM3 para P3, la hipótesis inicial.** Es la configuración `lfm3_composicion` del experimento. Con la misma entrada,
  ni el juez ni los guardrails de salida la separan de Qwen, y la ruta completa tarda más: p50 de 56.231 s contra
  50.528 s (evidencia abajo).
  Se conserva como respaldo de P3.
- **Un solo modelo (Qwen3.5-0.8B) para todo.** Ahorraría la memoria de LFM3 (1.389 GB cargado). No se adopta porque P4
  y P5 con Qwen no se midieron, y porque el gateway quedaría sin respaldo para las tareas de texto. Es candidato a
  trabajo futuro.
- **Solo LFM3:** no es posible, porque no acepta imágenes; haría falta otro modelo de visión.
- **Modelos más grandes**, por ejemplo una variante de 2B o un modelo de visión de 3B o más. Con los cuatro modelos
  actuales, el contenedor `ollama` ya llegó a un pico de 4.592 GiB con un límite de 5.0 GiB (evidencia abajo), así que
  no queda margen para uno mayor.
- **APIs de modelos en la nube:** descartadas por la regla de ejecución local (R2).

## Evidencia
**Fuente:** `evaluacion/resultados/r3_modelos.json`.
- Corrida del 2026-11-13 con `--fraccion 0.5`: 30 de las 60 fotos de `eval_fichas`.
- Prompts P2/P3 v4.
- El caso por caso está en `r3_modelos_detalle.csv` y `casos/fichas_*.jsonl`; las gráficas, en
  `evaluacion/graficas/r3_modelos_calidad.png` y `r3_modelos_latencia.png`.
- Las dos composiciones reciben exactamente la misma descripción P1, calculada una vez (`metricas.p1`: p50 de
  24.476 s).
- Calidad = promedio de fidelidad y relevancia del juez P7 (LFM3, temperatura 0) contra las descripciones humanas en
  español de XM3600.

| Configuración (`metricas.tabla`) | Parámetros / cuant. | Calidad 0–5 (IC95) | granite máx. | chrF | JSON válido a la 1.ª | Sin `requiere_revision` | Latencia de la ruta p50 · p95 | Memoria cargada (`/api/ps`) |
|---|---|---|---|---|---|---|---|---|
| `qwen_rapida`: Qwen, P2 con imagen y vecinos | 752.39M · Q8_0 | 4.8833 (4.7667–4.9667) | 0.7041 | 28.1953 | 1.0 | 0.6 | 31.291 s · 81.643 s | 0.83 GB |
| `qwen_composicion`: Qwen, P3 desde P1 (**elegida**) | 752.39M · Q8_0 | 4.95 (4.85–5.0) | 0.6753 | 24.2847 | 1.0 | 0.6667 | 50.528 s · 66.827 s | 0.83 GB |
| `lfm3_composicion`: LFM3, P3 desde el mismo P1 | 1.7B · Q4_K_M | 5.0 (5.0–5.0) | 0.6841 | 23.439 | 1.0 | 0.7333 | 56.231 s · 70.182 s | 1.389 GB |

- **Licencias:** Apache 2.0 (Qwen) y LFM Open License v1.0 (LFM3).
- **En disco:** 1.322 GB y 1.1 GB (`metricas.modelos`).
- Cuando se midió la memoria, los cuatro modelos estaban cargados a la vez (`metricas.memoria_api_ps`).

**Composición: LFM3 contra Qwen con la misma entrada** (`metricas.diferencias_pareadas.lfm3_composicion_menos_qwen_composicion`,
LFM3 − Qwen, por foto):
- **Juez:** diferencia 0.05, IC95 [0.0, 0.15], con 29 empates de 30. El juez da 5 a casi todo y es el mismo LFM3, así
  que casi no discrimina.
- **Métricas sin juez:** tampoco separan.
  - granite: 0.0089, IC95 [-0.0442, 0.0669];
  - chrF: -0.8457, IC95 [-7.7623, 6.7924].
- **Guardrails de salida:** quedan sin `requiere_revision` 22 fichas de LFM3 y 20 de Qwen. La diferencia pareada es
  0.0667, IC95 [-0.1333, 0.2667].
  - Los motivos son casi los mismos en las dos: poco apego visual y texto alternativo inconsistente con la descripción
    (`metricas.por_configuracion.*.motivos_revision`).
  - Qwen además tuvo una ficha con titular copiado de una etiqueta del prompt y una con un atributo sensible que la
    verificación quitó.

**Regla de decisión** (`metricas.conclusion.regla_de_decision`), escrita antes de esta corrida:
1. Gana la composición de mayor calidad del juez, si el IC95 de la diferencia pareada excluye 0.
2. Si no, la que deja más fichas sin revisión, si ese IC95 excluye 0.
3. Si tampoco, la de menor latencia p50.

Ningún IC95 excluye 0, así que decide la latencia: **Qwen compone P3** (p50 de 50.528 s contra 56.231 s).

**Por qué cambió la decisión (antes y después).** La primera corrida de R3 usó P2/P3 v2 (`r3_modelos_p2p3_v2.json`)
y tuvo dos lecturas:
- **Con la regla original** (juez → latencia) ganaba Qwen.
- **Con la regla corregida** (que agregó la tasa de guardrails, ya listada como métrica en el plan de evaluación)
  ganaba LFM3: 0.7 de sus fichas quedaban sin revisión, contra 0.4333 de las de Qwen.

Al leer los casos apareció un defecto que ningún guardrail medía: con v2, LFM3 copiaba el contexto del prompt.
- **Titulares:** usaba etiquetas como «Descripción objetiva de la imagen».
- **Palabras clave:** usaba titulares de fotos vecinas con su alias.
- **Fuentes:** citaba en bloque, así que sus fichas pasaban la verificación de fuentes sin que el contenido viniera de
  ellas.

El juez calificaba esas fichas con 5. En las mismas 30 fotos, la verificación encuentra copias en 23 fichas de
`lfm3_composicion` con v2 y en 0 con v4 (`evaluacion/resultados/antes_despues_prompts.json` →
`configuraciones.lfm3_composicion`).

Para corregirlo:
- se agregó la verificación `copia_contexto` (ADR-05);
- se ajustaron los prompts en 10 fotos que no son de evaluación (`ajuste_prompts_p2p3_v3.json` y `_v4.json`);
- se repitió R3 con v4.

Sin el defecto, la ventaja de LFM3 desaparece. **La regla no se cambió por segunda vez:** ya se había corregido una
vez después de ver datos, y ajustarla otra vez para conservar la hipótesis inicial le quitaría validez al experimento.

**Ruta rápida contra ruta completa** (`metricas.diferencias_pareadas.qwen_rapida_menos_qwen_composicion`):
- **Latencia:** la ruta rápida tiene una p50 de 31.291 s, contra 50.528 s de la completa.
- **Calidad del juez:** 4.8833 contra 4.95 (diferencia -0.0667, IC95 [-0.2167, 0.0833]).
- **Por qué su p95 llega a 81.643 s:** 8 de 30 fichas volvieron a hacerse por la ruta completa, porque el texto
  alternativo no se apegaba a la imagen (`ruta_final` y `motivos_revision` de `qwen_rapida`).
- **Titular copiado:** en 7 de 30 fichas la ruta rápida copió el de una foto similar. `copia_contexto` lo vacía y la
  ficha queda para el archivista.

El enrutador (ADR-03) decide foto por foto cuál ruta conviene.

**Datos de viabilidad ya medidos.** No sustituyen al experimento: son muestras pequeñas y no califican la calidad.
Fuente: `evaluacion/resultados/h0.json` y `evaluacion/resultados/h0_memoria_por_modelo.txt`.

| Medición | Qwen3.5-0.8B | LFM3-1.7B | Fuente |
|---|---|---|---|
| P1 con imagen a 512 px: JSON válidos, p50 y p95 | 8/8 · 34.28 s · 38.499 s | — | `verificaciones.0.6.p1_por_lado.512` |
| P3 (ficha completa, hasta 600 tokens): JSON válidos, p50 y p95 | 5/5 · 35.583 s · 42.178 s (solo texto) | 8/8 · 39.351 s · 59.444 s | `verificaciones.0.6.p3_qwen_texto` y `verificaciones.0.6.p3_lfm3` |
| Tamaño en disco (bytes) | 1322069277 | 1099638680 | `modelos_descargados` |
| Memoria residente del proceso `llama-server` (VmRSS) | 1617684 kB | 1438764 kB | `h0_memoria_por_modelo.txt` |

- Con los cuatro modelos cargados y fichas en curso, el pico del contenedor `ollama` fue de 4.592 GiB con un límite de
  5.0 GiB (`h0.json` → `verificaciones.0.5.docker_stats.pico_por_contenedor_gib` y `limite_por_contenedor_gib`; ADR-12).
- Esas mediciones se hicieron en una VM de Docker con CPU Apple `aarch64` de 8 núcleos (`h0.json` →
  `hardware_contenedor`). La demo será en una laptop Windows x86, donde la latencia se medirá de nuevo.

## Consecuencias
- **Se gana:**
  - la ficha completa es más rápida;
  - un solo modelo, de menos de mil millones de parámetros, ve y compone;
  - el gateway tiene un respaldo real para P3, con otro modelo y otra familia.
- **Se sacrifica:**
  - la memoria de LFM3 (1.389 GB) se paga por P4, P5 y el respaldo, no por la tarea principal;
  - la ruta completa sigue encadenando dos llamadas a Qwen, P1 y luego P3.
  - Por eso el enrutador manda a la ruta rápida las fotos cuyos vecinos coinciden (ADR-03), y los lotes corren en
    segundo plano (ADR-08).
- **Por qué el compromiso es adecuado para el dominio y el equipo:**
  - catalogar no es una tarea de tiempo real, y el archivista revisa y valida cada ficha antes de publicarla;
  - la calidad de modelos tan pequeños se compensa con el RAG (ejemplos y normas), los guardrails de salida y la
    revisión humana;
  - ningún modelo mayor cabe en la laptop junto con los otros tres.
- **Riesgos:**
  - Con tan pocos parámetros, las fichas pueden omitir detalles o inventarlos (alucinación).
  - Qwen compuso una ficha con un atributo sensible. La verificación `atributos_sensibles` lo quitó y marcó la ficha
    (`motivos_revision` de `qwen_composicion`). La política de privacidad depende de esa verificación, no del modelo.
  - El juez P7 es LFM3 y su calificación satura en 5. Aquí no decidió, y se contrasta con métricas sin juez y con la
    revisión manual (`evaluacion/revision_manual/`).
  - Las cifras son de 30 fotos y la corrida completa de 60 puede mover los intervalos. Con la regla escrita, un cambio
    en ese sentido podría devolver P3 a LFM3, que sigue cargado como respaldo.
  - La licencia LFM Open License v1.0 está pendiente de revisión por el autor para el uso académico previsto.
