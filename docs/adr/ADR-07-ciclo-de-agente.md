# ADR-07: Ciclo de agente híbrido adaptativo: la ruta pipeline como reformulación, con MAX_ITER = 2

**Estado:** Propuesta
**Fecha:** 2026-11-08
**Atributos de calidad en juego:** calidad de la ficha en fotos poco representadas en el archivo, latencia añadida,
predictibilidad del flujo, trazabilidad de cada decisión

## Contexto
El RAG de ejemplos busca fotos parecidas ya catalogadas para guiar la ficha nueva. Cuando la foto viene de una región,
una cultura o un tipo de escena que el archivo casi no tiene, los vecinos de la ruta unificada (imagen→imagen e
imagen→texto) son malos: la ficha se apoya en ejemplos que no aplican y el enrutador recibe señales engañosas. El curso
pide un ciclo de agente con condición de salida y un máximo de iteraciones, y el diseño de Fototeca Viva quiere probar
que las dos arquitecturas de búsqueda (unificada y pipeline, ADR-02) se complementan.

## Decisión
Una **máquina de estados explícita** en `servicio/fototeca/orquestacion/flujo_ficha.py`:

```
RECUPERAR_EJEMPLOS → EVALUAR_RECUPERACION ─(pobre y iteraciones < MAX_ITER)→ REFORMULAR → EVALUAR_RECUPERACION
                                          └(si no)→ ENRUTAR → GENERAR → …
```

- **Recuperación pobre:** top-1 < τ_ret, o top-1 − top-5 < δ_margen (δ empieza en 0.02). Las dos señales se miden
  siempre con el coseno imagen–imagen entre la foto y cada vecino, para comparar las iteraciones en la misma escala.
  τ_ret es el percentil 10 del top-1 sobre la partición `nuevas` (sin las fotos de evaluación ni las regiones
  excluidas), calculado por `scripts/calibrar.py`. Sin τ_ret calibrado el ciclo no se activa.
- **REFORMULAR es la ruta pipeline:** Qwen describe la foto (P1, una sola vez por ficha; la ruta completa la reutiliza),
  la descripción se busca como texto en `fotos_txt` y el resultado se fusiona con RRF (k = 60) con las listas anteriores.
  En la segunda iteración se buscan por separado hasta 5 `elementos` de P1.
- **Condición de salida:** la recuperación deja de ser pobre, se alcanza `MAX_ITER = 2` (`agente.max_iter`), o P1 falla
  (tiempo agotado o sin modelo), en cuyo caso la ficha sigue con una advertencia.
- **Trazabilidad:** cada transición se registra en T1 (con el top-1 antes y después de reformular) y la respuesta trae
  `meta.iteraciones_agente`, `meta.transiciones` y `meta.recuperacion`.
- El mismo patrón, más simple, existe en la búsqueda por texto: si ningún resultado supera τ_busqueda, P5 (LFM3)
  propone hasta 3 reformulaciones y se vuelve a buscar, con un máximo de 2 iteraciones.

Es el diseño **híbrido adaptativo**: unificado por defecto y pipeline solo cuando hace falta.

## Alternativas
- **Pipeline siempre:** pagaría la descripción de P1 en cada foto aunque la recuperación unificada ya fuera buena.
- **Nunca reformular:** las fotos poco representadas quedarían con vecinos que no aplican.
- **Un agente planificador con un modelo de lenguaje** (que decida en cada paso qué herramienta usar): más llamadas a
  modelos en CPU y un flujo menos predecible y más difícil de probar; la máquina de estados hace explícitos los pasos y
  sus límites.
- **Más iteraciones:** cada iteración extra cuesta embeddings y búsquedas, y la descripción de P1 ya se aprovechó en la
  primera; el experimento dirá si la segunda aporta.

## Evidencia
**pendiente:** `evaluacion/resultados/agente.json`, sobre las 20 fotos de `regiones_excluidas` que están en
`eval_fichas` más 30 de la misma partición: porcentaje de casos que activan el ciclo; porcentaje que **mejora** después
de reformular (el acierto@5 de vecinos pasa de 0 a 1, o el top-1 sube más que δ); iteraciones promedio; latencia
añadida; y calidad de la ficha con el ciclo contra sin él (`MAX_ITER = 0`). El valor calibrado de τ_ret saldrá en
`evaluacion/resultados/calibracion_h4.json`.

Costo de referencia de una reformulación, medido en H0: P1 de Qwen con la imagen a 512 px tuvo una p50 de 34.28 s y un
embedding de texto de EmbeddingGemma-2, una p50 de 0.159 s (`evaluacion/resultados/h0.json` → `verificaciones.0.6`).

## Consecuencias
- **Se gana:** las fotos difíciles reciben mejores ejemplos sin pagar la ruta pipeline en todas las demás; cada decisión
  del agente queda en la traza y se puede mostrar en la demo (pie técnico).
- **Se sacrifica:** una ficha que entra al ciclo paga P1 aunque después vaya por la ruta rápida.
- **Riesgos:** si el archivo no tiene ninguna foto parecida, reformular no inventa vecinos buenos: el ciclo termina por
  MAX_ITER y la ficha depende más de la descripción de P1 y de las reglas; los guardrails de salida y la revisión humana
  siguen siendo la última defensa.
