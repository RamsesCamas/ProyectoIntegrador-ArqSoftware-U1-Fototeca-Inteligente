# ADR-03: Criterio de los enrutadores de fichas (consenso y acuerdo de los vecinos) y de búsquedas

**Estado:** Propuesta
**Fecha:** 2026-11-08
**Atributos de calidad en juego:** latencia (evitar llamadas costosas), calidad de la ficha, exactitud del enrutador,
seguridad (texto visible en la foto), explicabilidad de la decisión

## Contexto
Las dos rutas de la ficha cuestan muy distinto: la **rápida** hace una sola llamada (P2, Qwen con la imagen y las fichas
vecinas) y la **completa** hace dos (P1 con Qwen y P3 con LFM3; ADR-01). En las búsquedas pasa lo mismo: una búsqueda
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
**rápida**. Si τ_consenso no está calibrado, se elige la completa, que es la conservadora. τ_acuerdo empieza en 0.25 (valor
por defecto del código) y τ_consenso en la mediana del consenso sobre la partición `nuevas` (`scripts/calibrar.py`,
que escribe `evaluacion/resultados/calibracion_h4.json`); los dos se recalibran con la evaluación y quedan en
`servicio/config/parametros.yaml`. Las señales, los umbrales y las razones viajan en `meta.senales_enrutador` y
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
  de `excluir` y el filtro de personas penalizan el puntaje de los resultados que los contradicen.

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
**pendiente:** `evaluacion/resultados/enrutador.json`:
- **Fichas:** se ejecutan las dos rutas sobre `eval_fichas`; la ruta «correcta» de cada foto es la rápida si su calidad
  queda a 0.5 puntos o menos de la completa. Se reporta el porcentaje de fotos enviadas a la ruta correcta, la latencia
  de cada ruta, la calidad final contra «siempre rápida» y «siempre completa», y el par (τ_consenso, τ_acuerdo) que
  maximiza la exactitud con la restricción de que la latencia media no pase de la mitad de «siempre completa».
- **Búsquedas:** exactitud sobre 40 consultas etiquetadas (20 simples y 20 complejas), latencia de cada ruta y R@10 de
  las complejas con P4 contra sin P4.

Costo de cada llamada medido en H0 (referencia del ahorro posible, `evaluacion/resultados/h0.json` →
`verificaciones.0.6`): P1 de Qwen con imagen a 512 px, p50 de 34.28 s; P3 de LFM3, p50 de 39.351 s; embedding de texto
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
  mitiga ese caso reintentando por la ruta completa (ADR-05).
