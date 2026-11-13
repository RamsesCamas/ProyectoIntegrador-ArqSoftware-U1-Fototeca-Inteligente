# ADR-03: Criterio de los enrutadores de fichas (consenso y acuerdo de los vecinos) y de búsquedas

**Estado:** Aceptada
**Fecha:** 2026-11-08 (evidencia: 2026-11-13)
**Atributos de calidad en juego:** latencia (evitar llamadas costosas), calidad de la ficha, exactitud del enrutador,
seguridad (texto visible en la foto), explicabilidad de la decisión

## Contexto
Las dos rutas de la ficha cuestan muy distinto: la **rápida** hace una sola llamada (P2, Qwen con la imagen y las fichas
vecinas) y la **completa** hace dos (P1 y P3 con Qwen; ADR-01). En las búsquedas pasa lo mismo: una búsqueda
**simple** solo embebe el texto y consulta la base vectorial, mientras que una **compleja** llama antes a P4 (LFM3) para
descomponerla. Hace falta un criterio explícito, barato de calcular y registrado en la traza para decidir cada caso.

## Decisión
**Enrutador de fichas** (`servicio/fototeca/modelos/enrutador_fichas.py`). Decide después de recuperar los 5 vecinos
(por eso la recuperación va antes que el enrutamiento; diagrama 7), con cuatro señales:
- `consenso`: media del coseno imagen–imagen de los vecinos;
- `acuerdo`: Jaccard medio entre los conjuntos de palabras clave de cada par de vecinos;
- `texto_visible`: el guardrail de entrada detectó texto escrito en la foto;
- `margen`: similitud del primer vecino menos la del quinto (se registra para el análisis).

Regla: si hay texto visible, o `acuerdo < τ_acuerdo`, o `consenso < τ_consenso`, la ruta es **completa**; si no, es
**rápida**. Valores vigentes, calibrados en la evaluación: τ_consenso = 0.6768 y τ_acuerdo = 0.0 (este último deja
sin efecto la señal de acuerdo; ver Evidencia). Si τ_consenso no está calibrado, se elige la completa, que es la conservadora. τ_acuerdo empieza en 0.25 (valor
por defecto del código) y τ_consenso en la mediana del consenso sobre la partición `nuevas` (`scripts/calibrar.py`,
que escribe `evaluacion/resultados/calibracion_h4.json`); los dos se recalibran con la evaluación y quedan en
`servicio/config/calibracion.yaml` (lo escribe `scripts/aplicar_calibracion.py`, con el archivo de origen de cada valor). Las señales, los umbrales y las razones viajan en `meta.senales_enrutador` y
`meta.razones_enrutador`.
Una foto con texto visible siempre va por la completa: así Qwen nunca recibe ese texto como posible instrucción en la
ruta rápida y P3 lo recibe aislado entre delimitadores (ADR-05).

**Enrutador de búsquedas** (`servicio/fototeca/modelos/enrutador_busquedas.py`):
- búsqueda por foto: ruta `imagen`, sin modelo de lenguaje;
- búsqueda por texto: **compleja** si tiene negación («sin», «excepto», «que no»…), más de 2 restricciones de lugar,
  momento, cantidad o atributo, más de 12 palabras, o si se parece más al centroide de los prototipos de consultas
  complejas que al de las simples (colección `prototipos`); si no, **simple**. Esos límites son los valores por defecto
  del código y se pueden ajustar en `parametros.yaml` (`enrutador_busquedas.*`).
- La compleja pasa por P4 (LFM3, con Qwen de respaldo; si ambos fallan, se busca con el texto original). Los términos
  de `excluir` y el filtro de personas penalizan el puntaje de los resultados que los contradicen. El filtro de
  personas de P4 solo se respeta si la consulta menciona personas (`FlujoBusqueda._filtro_personas`), porque LFM3 casi
  nunca lo deja en `null` (ver Evidencia).

## Alternativas
- **Siempre la ruta completa:** la calidad esperada más alta, pero duplica las llamadas a modelos en cada ficha.
- **Siempre la ruta rápida:** la más barata, pero deja la ficha en el modelo más pequeño y expone a Qwen al texto de la
  foto.
- **Enrutar con un modelo de lenguaje (clasificador por prompt):** agrega una llamada de decenas de segundos en CPU justo
  para ahorrar llamadas.
- **Clasificador entrenado:** no hay datos etiquetados ni se hace fine-tuning en este proyecto.
- **P4 en todas las búsquedas:** pondría un modelo de lenguaje en el camino de cada búsqueda simple, que debe responder
  en segundos.

## Evidencia
**Valores iniciales calibrados** con las 660 fotos de `nuevas` que no están en `eval_fichas`
(`evaluacion/resultados/calibracion_h4.json`):
- **τ_consenso = 0.7864**, la mediana del consenso entre vecinos (p25 0.7582, p75 0.8152): de entrada, la mitad de las
  fotos va a la ruta rápida;
- **τ_busqueda = 0.6086**, el piso de relevancia de la búsqueda: el p95 de la similitud texto→imagen entre fotos y
  descripciones **ajenas** (ruido) en una muestra de 600 fotos del archivo. Un resultado se muestra solo si supera lo que
  alcanza el 95 % de los pares no relacionados; si ninguno lo supera, la búsqueda reformula con P5 (máximo 2 veces). Con
  ese τ, una consulta deja en promedio 30.98 candidatas de 600. La primera versión usaba el p5 de los pares **propios**
  (0.6635) y solo dejaba coincidencias casi exactas: 3.212 fotos de 600 por consulta
  (`evaluacion/resultados/calibracion_h4_piso_busqueda.json`).

El valor final de τ_consenso y τ_acuerdo sale de la validación cruzada de 5 pliegues del experimento del enrutador.

**Fichas** (`evaluacion/resultados/enrutador.json` → `metricas.fichas`; 30 fotos de `eval_fichas`, prompts P2/P3 v4, P3
compuesto por Qwen). Las dos rutas se ejecutan sobre todas las fotos. La ruta «correcta» de cada foto es la rápida si su
calidad del juez queda a 0.5 puntos o menos de la completa. Se busca el par (τ_consenso, τ_acuerdo) que maximiza la
exactitud con la restricción de que la latencia media no pase de la mitad de «siempre completa».

| Estrategia (`metricas.fichas.estrategias`) | Exactitud | A la rápida | Calidad (juez) | granite | Latencia media · p50 |
|---|---|---|---|---|---|
| Siempre rápida | 0.9667 | 1.0 | 4.8833 | 0.7041 | 43.3366 s · 31.291 s |
| Siempre completa | 0.0333 | 0.0 | 4.95 | 0.6753 | 51.425 s · 50.528 s |
| Umbrales de H4 (0.7864; 0.25) | 0.2 | 0.1667 | 4.9833 | 0.6858 | 47.876 s · 46.464 s |
| **Umbrales elegidos** (validación cruzada, fuera de muestra) | **0.8333** | 0.8667 | 4.8833 | 0.716 | 43.2836 s · 32.764 s |
| Oráculo (la ruta correcta de cada foto) | 1.0 | 0.9667 | 4.9333 | 0.7078 | 44.4787 s · 31.291 s |

- **Ninguno de los 279 pares cumple la restricción de latencia** (`barrido.pares_factibles` = 0; límite 25.713 s). Ni
  siquiera «siempre rápida» la cumple, porque 8 de 30 fichas rápidas escalaron a la completa por poco apego visual
  (`rapida_que_escalo_a_completa`). Se eligió el par de mayor exactitud y quedó registrada la advertencia.
- Los cinco pliegues eligen τ_consenso 0.6768 o 0.6771 y τ_acuerdo 0.0 (`validacion_cruzada.por_pliegue`).
- 29 de 30 fotos tienen como «correcta» la rápida (`ruta_correcta`), y 4 de 30 tienen texto visible, que siempre va
  por la completa.

**Lectura (fichas).** La etiqueta de «ruta correcta» depende del juez, y el juez casi no distingue entre rutas (4.8833
contra 4.95). Por eso la calibración manda a la ruta rápida al 86.67 % de las fotos y apaga la señal de acuerdo. Lo que
se gana es medible: la latencia media baja de 47.876 s a 43.2836 s respecto de los umbrales de H4, y la similitud
granite con las referencias humanas sube de 0.6858 a 0.716. Lo que se paga, también: en la ruta rápida Qwen copió el
titular de una foto similar en 7 de 30 fichas, que quedan para que el archivista escriba el titular (ADR-01). Si el
juez no discrimina, la calibración tampoco. La contraprueba es la revisión manual de 20 fichas
(`evaluacion/revision_manual/plantilla_fichas.csv`). La primera corrida, con fichas de P2/P3 v2 que copiaban el
contexto (ADR-05, `copia_contexto`), se conserva en `enrutador_p2p3_v2.json`.

**Búsquedas** (`evaluacion/resultados/enrutador.json` → `metricas.busquedas`; corrida del 2026-11-13 con
`--fraccion 0.5`: 25 consultas etiquetadas, 10 simples y 15 complejas, sobre una galería de 1,000 fotos subidas; ninguna
foto relevante quedó fuera de la galería; corrida con el filtro de personas corregido):

| Medición | Simples (n = 10) | Complejas (n = 15) |
|---|---|---|
| Enviadas a la ruta correcta | 0.7 (3 se fueron a la compleja) | 0.9333 (1 se fue a la simple) |
| R@10 por la ruta simple (sin P4) | 1.0 | 0.8556 |
| R@10 por la ruta compleja (con P4) | 1.0 | 0.8556 (IC95 0.6889–1.0) |
| MRR sin P4 · con P4 | 1.0 · 1.0 | 0.7541 · 0.8262 |

- **Exactitud del enrutador:** 0.84 sobre las 25 consultas.
- **Latencia por ruta** (`latencia_por_ruta_s`): la simple tiene una p50 de 0.26 s y una p95 de 0.363 s; la compleja,
  con P4, una p50 de 6.003 s y una p95 de 6.733 s.
- **P4 en las complejas** (`complejas_con_p4_menos_sin_p4`): el R@10 no cambia en ninguna de las 15 consultas
  (diferencia pareada 0.0), pero el MRR sube de 0.7541 a 0.8262: la penalización de lo excluido sube la foto correcta en
  la lista. En 5 de las 25 consultas P4 encontró términos que excluir (`p4.con_terminos_excluidos`).
- **Filtro de personas:** en la primera corrida, P4 lo fijó en las 25 consultas complejas, incluso en «domo de torre de
  telecomunicaciones» (`enrutador_p2p3_v2.json` → `metricas.busquedas.p4`). Con la corrección, solo queda en 13 de 25,
  las que mencionan personas (`p4.con_filtro_de_personas`). El MRR con P4 pasó de 0.8229 a 0.8262 (la galería también
  ganó las 5 fotos que faltaban).

**Lectura (búsquedas).** P4 no encuentra fotos que la búsqueda simple no encuentre; lo que aporta es el orden y la
consulta interpretada que la web muestra, a cambio de unos 5 s más por consulta. Por eso P4 queda solo para las
consultas que el enrutador marca como complejas. El error más frecuente del enrutador es caro pero inocuo: 3 de 10
consultas simples pagaron P4 sin necesidad.

Costo de cada llamada medido en H0 (referencia del ahorro posible, `evaluacion/resultados/h0.json` →
`verificaciones.0.6`): P1 de Qwen con imagen a 512 px, p50 de 34.28 s; P3 de Qwen solo texto, p50 de 35.583 s (de LFM3,
39.351 s); embedding de texto
de EmbeddingGemma-2, p50 de 0.159 s.

## Consecuencias
- **Se gana:** una decisión explicable (cada ficha dice por qué tomó su ruta), que no cuesta llamadas a modelos y que
  ahorra la llamada más cara cuando el archivo ya tiene fotos parecidas bien catalogadas.
- **Se sacrifica:** las señales dependen de la calidad del archivo; un archivo con pocas fichas validadas manda más fotos
  a la ruta completa. Las reglas de búsqueda son heurísticas en español.
- **Por qué el compromiso es adecuado para el dominio y el equipo:** en un archivo institucional muchas fotos se parecen
  (mismos eventos, mismos lugares), así que la ruta rápida apoyada en vecinos validados cubre una parte del trabajo; en
  CPU, cada llamada evitada se nota.
- **Riesgos:** umbrales mal calibrados pueden mandar a la ruta rápida fotos difíciles; el guardrail `apego_visual`
  mitiga ese caso reintentando por la ruta completa (ADR-05). La calibración depende de un juez que satura; con 30
  fotos, τ_consenso puede moverse en la corrida completa de 60.
