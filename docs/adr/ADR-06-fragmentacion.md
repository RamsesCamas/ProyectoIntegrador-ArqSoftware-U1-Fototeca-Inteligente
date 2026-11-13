# ADR-06: Fragmentación: una regla por fragmento en las normas y un concepto por documento en el tesauro

**Estado:** Aceptada
**Fecha:** 2026-11-08
**Atributos de calidad en juego:** precisión de la recuperación de normas, trazabilidad de las fuentes (citas por id),
presupuesto del prompt de LFM3, cumplimiento del tamaño mínimo del corpus (R1)

## Contexto
El RAG normativo recupera reglas de IPTC Photo Metadata 2025.1, del tutorial de imágenes de W3C WAI, de WCAG 2.2
(criterio 1.1.1) y de DCMI Terms, y términos del Tesauro de la UNESCO. Cada fragmento recuperado se entrega al modelo con
un id estable (`regla:…`, `tesauro:…`) que la ficha cita como fuente de un campo, y que el guardrail `fuentes` verifica.
Si un fragmento mezcla varias reglas, la cita deja de decir de cuál salió el dato. Además, el prompt de LFM3 tiene un
presupuesto de unos 2,000 tokens (valor por defecto del ensamblador en `servicio/fototeca/contexto/ensamblador_prompt.py`)
que comparten las fichas vecinas, las reglas y los términos.

## Decisión
- **Normas:** una regla o un campo por fragmento, porque son unidades atómicas (una propiedad de IPTC, un término de
  DCMI, una sección del tutorial de W3C). Objetivo de 300 a 800 caracteres sin solapamiento; una sección de más de 1,200
  caracteres se divide por párrafos de 800 como máximo, con un solapamiento del 15 % cortado en límite de palabra. Cada
  fragmento de una sección dividida lleva al inicio su encabezado («Norma — sección»), para que un fragmento suelto diga
  de dónde viene. Metadatos: `fuente`, `url`, `seccion`, `campo_iptc`, `licencia` y `version_corpus`.
- **Tesauro:** un concepto por documento, con el texto «{etiqueta preferida}. Sinónimos: {etiquetas alternativas}.
  {nota de alcance}» en español; los conceptos sin etiqueta en español se descartan y se cuentan.
- **Una sola implementación** (`servicio/fototeca/contexto/fragmentador.py`) para la preparación del corpus y para las
  normas que se suben por `POST /documentos` (HTML, Markdown, PDF o TXT).
- **Recuperación:** k = 4 reglas por ficha, con la consulta «texto alternativo y descripción de imagen informativa» más
  las palabras clave de los vecinos (`servicio/fototeca/contexto/recuperador_normas.py`).

## Alternativas
- **Fragmentos de tamaño fijo (500 a 1,000 caracteres con 10 a 20 % de solapamiento):** juntarían varias propiedades de
  IPTC o varios términos de DCMI en un fragmento y la cita `regla:id` sería ambigua.
- **Un fragmento por página o por sección completa:** demasiado largo para el presupuesto del prompt y con la regla útil
  diluida entre texto que no aplica.
- **Indexar el tesauro con su jerarquía completa:** el modelo solo necesita la etiqueta, los sinónimos y la nota de
  alcance para normalizar palabras clave.

## Evidencia
Fuente: `evaluacion/resultados/corpus_r1.json` (versión del corpus `e1879cf60262`).

| Medición | Valor |
|---|---|
| Documentos fuente sin el tesauro | 13 |
| Fragmentos | 412 |
| Caracteres sin el tesauro | 177118 |
| Páginas aproximadas sin el tesauro (2,000 caracteres por página) | 88.6, cumple R1 (`cumple_r1: true`) |
| Longitud de los fragmentos: mínima, media y máxima (caracteres) | 98 · 429.9 · 1142 |
| Fragmentos de 300 a 800 caracteres · menores de 300 · mayores de 800 | 200 · 157 · 55 |
| Fragmentos de IPTC · WCAG 1.1.1 · DCMI | 196 · 44 · 129 |
| Fragmentos de las 10 páginas del tutorial de W3C | 5, 4, 5, 5, 7, 6, 2, 1, 3 y 5 |
| Conceptos del tesauro · con etiqueta en español · descartados | 4500 · 4500 · 0 |

- Los fragmentos de menos de 300 caracteres son, sobre todo, términos de DCMI y propiedades de IPTC cortos: la regla
  prioriza la atomicidad sobre el tamaño objetivo. Los mayores de 800 son secciones de hasta 1,200 caracteres, que por
  regla no se dividen, o partes de una sección dividida que suman el solapamiento y el encabezado; ninguno llega a 1,200
  (el máximo medido es 1142).
- **Calidad de la recuperación de normas** (`evaluacion/resultados/r3_embeddings.json` → `metricas.normas`; 20
  consultas en español con su regla esperada, corrida al 50 % de los conjuntos, que no recorta estas 20): con k = 4,
  el valor de producción, EmbeddingGemma-2 recupera la regla esperada en 0.65 de las consultas (acierto@1 0.25,
  acierto@10 0.8); granite, en 0.65 (0.35 y 0.75). Por tipo de consulta, las 8 de **metadatos** IPTC y DCMI llegan a
  1.0 con k = 4 en EmbeddingGemma-2, pero las 12 de **texto alternativo** solo a 0.4167 (acierto@10 0.6667). Las
  reglas de texto alternativo vienen sobre todo del tutorial de W3C, en inglés, y las consultas son en español: es el
  riesgo que esta sección ya anotaba. No se cambia la fragmentación, porque el problema está en el idioma y no en el
  tamaño de los fragmentos; el guardrail `fuentes` evita que una regla mal recuperada se cite sin estar en el
  contexto.

## Consecuencias
- **Se gana:** cada campo de la ficha puede citar exactamente la regla que aplicó, y el guardrail `fuentes` puede
  verificar esa cita; la misma fragmentación sirve para las normas que el archivista suba después.
- **Se sacrifica:** los fragmentos muy cortos llevan menos contexto y pueden recuperarse peor con consultas largas.
- **Riesgos:** las páginas de W3C están en inglés (no hay traducción al español) y las consultas son en español: la
  recuperación depende de que el embedding sea multilingüe; el experimento de R3 lo mide.
