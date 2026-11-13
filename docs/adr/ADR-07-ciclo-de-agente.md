# ADR-07: Ciclo de agente híbrido adaptativo: la ruta pipeline como reformulación, con MAX_ITER = 2

**Estado:** Aceptada (con beneficio no demostrado en este archivo; ver Evidencia)
**Fecha:** 2026-11-08 (evidencia: 2026-11-13)
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
**Experimento** (`evaluacion/resultados/agente.json`, corrida del 2026-11-13 con `--fraccion 0.5`). Se usaron 25
fotos de `regiones_excluidas`: 10 de `eval_fichas` y 15 de `agente_extra`. Cada foto se catalogó con el ciclo (el flujo
de producción) y sin él (`MAX_ITER = 0`). La gráfica está en `evaluacion/graficas/agente_ciclo.png`.

| Medición | Resultado |
|---|---|
| Activan el ciclo (`activa_ciclo`) | 0.12 (3 de 25), con 2 iteraciones cada una |
| Mejoran al reformular, entre las que lo activan | 0.0 (0 de 3): ni el acierto@5 de vecinos pasa de 0 a 1 ni el top-1 sube más que δ = 0.02 |
| Cambio del top-1 en las que lo activan | media -0.0133 |
| Latencia añadida en las que lo activan | media 27.631 s, p50 24.167 s |
| Calidad con y sin ciclo (juez · granite) | 4.94 · 0.7184 contra 4.94 · 0.7239; diferencia pareada de granite -0.0055, IC95 [-0.0407, 0.0273] |
| Fichas sin `requiere_revision` | 14 contra 15 de 25 |

**Lectura.** En este archivo, reformular con la descripción de P1 (la ruta pipeline) no encontró mejores ejemplos en
ninguna de las 3 fotos que activaron el ciclo, y la calidad de la ficha no cambió. El criterio de mejora tenía poco
margen: el acierto@5 de vecinos ya era 1.0 antes de reformular en las 25 fotos (`acierto5_vecinos.inicial_todos`). Es decir,
aun sin su región en el archivo, estas fotos tienen vecinos que el criterio considera pertinentes, probablemente por el
contenido de la escena. El ciclo se conserva porque cumple tres funciones:
- **detecta la recuperación pobre** y la deja en la traza;
- **termina siempre:** MAX_ITER = 2 y la condición de salida se cumplieron en los 3 casos;
- **adelanta P1**, así que la descripción objetiva entra al contexto antes de enrutar.

Que mejore la ficha no está demostrado. En la latencia media de las 25 fotos (18.631 s más con el ciclo) también
influyen los cambios de ruta y los reintentos por apego visual de las fotos que no lo activaron, así que la cifra de
las 3 que sí lo activaron es la que se atribuye al ciclo.

**τ_ret calibrado** con las 660 fotos de `nuevas` que no están en `eval_fichas`
(`evaluacion/resultados/calibracion_h4.json`): la similitud top-1 de recuperación tiene p10 = 0.7634, p50 = 0.8223 y
mínimo 0.6943, así que **τ_ret = 0.7634** (p10). Con ese τ y el margen δ, el 11.52 % de esas fotos se consideraría
recuperación pobre y activaría el ciclo (`fraccion_pobre_con_tau_ret_y_delta` = 0.1152).

**Aceptación de H4** (`evaluacion/resultados/h4_aceptacion.json`). Como τ_ret es el p10, elegir al azar una foto de
`regiones_excluidas` activa el ciclo solo a veces. La aceptación elige, entre las 250 candidatas que no están en
conjuntos de evaluación, las 40 que cumplen la regla del flujo (`recuperacion_pobre`) y quedan lejos de los umbrales
de fuera de dominio y de texto visible. Con la de menor top-1 (0.6895 previsto) el ciclo hizo **2 iteraciones** con 2
reformulaciones en la traza, y la recuperación siguió pobre (top-1 0.6719, top-5 0.5901). Reformular no garantiza
encontrar mejores ejemplos cuando el archivo de verdad no tiene fotos de esa región; cuánto mejora en promedio lo mide
`agente.json`.

Costo de referencia de una reformulación, medido en H0: P1 de Qwen con la imagen a 512 px tuvo una p50 de 34.28 s y un
embedding de texto de EmbeddingGemma-2, una p50 de 0.159 s (`evaluacion/resultados/h0.json` → `verificaciones.0.6`).

## Consecuencias
- **Se gana:** un flujo con condición de salida y máximo de iteraciones verificables; cada decisión del agente queda en
  la traza y se puede mostrar en la demo (pie técnico). Que las fotos difíciles reciban mejores ejemplos era la
  hipótesis, y en este archivo no se confirmó (Evidencia).
- **Se sacrifica:** una ficha que entra al ciclo paga P1 aunque después vaya por la ruta rápida.
- **Riesgos:** si el archivo no tiene ninguna foto parecida, reformular no inventa vecinos buenos: el ciclo termina por
  MAX_ITER y la ficha depende más de la descripción de P1 y de las reglas; los guardrails de salida y la revisión humana
  siguen siendo la última defensa. Trabajo futuro: probar otra reformulación (por ejemplo, ampliar k o buscar por
  descripción en `fotos_desc_qwen`) con un criterio de mejora que no esté saturado.
