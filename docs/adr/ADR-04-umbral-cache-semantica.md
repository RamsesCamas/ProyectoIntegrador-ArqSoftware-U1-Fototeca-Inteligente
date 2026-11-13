# ADR-04: Umbral de la caché semántica τ_dup, su TTL e invalidación por etiquetas

**Estado:** Aceptada
**Fecha:** 2026-11-08 (evidencia: 2026-11-13)
**Atributos de calidad en juego:** latencia de la ficha repetida, corrección (respuestas incorrectas servidas desde la
caché), recall de la detección de duplicados, consistencia después de cambios en el archivo, el corpus o la
configuración

## Contexto
Una ficha nueva cuesta decenas de segundos en CPU (ADR-01). Los archivos institucionales tienen fotos repetidas y
versiones recortadas, recomprimidas o con otro brillo de la misma foto; para ellas no vale la pena volver a llamar a los
modelos. Pero dos fotos distintas del mismo lugar también se parecen, y servirles la misma ficha sería un error. Además,
la ficha en caché debe dejar de servirse cuando cambia algo de lo que dependía.

## Decisión
**Caché de fichas** (`servicio/fototeca/cache/cache_fichas.py`):
- **Exacta:** clave = `sha256` de los bytes de la imagen + versión de configuración (hash de los parámetros, los modelos,
  las versiones de los prompts y la versión del corpus).
- **Semántica:** vector de la imagen en EmbeddingGemma-2 contra el umbral **τ_dup = 0.95** (calibrado con el barrido
  de abajo; el valor inicial era 0.97 en `servicio/config/parametros.yaml`, `cache.fichas.tau_dup`, y
  `scripts/aplicar_calibracion.py` escribe el calibrado en `config/calibracion.yaml`), en dos niveles: (1) fichas generadas antes por el
  servicio, guardadas en SQLite con TTL de 7 días y solo de la misma versión de configuración; (2) fichas **validadas**
  del archivo en Qdrant (`fotos_img` con `validada = true`), que no expiran porque las respalda una persona.
- **Un acierto semántico es también una detección de duplicado:** la respuesta lleva `duplicado_de` (documento y
  similitud) y la advertencia «Posible duplicado de …». El mismo τ_dup decide los casi duplicados al ingerir
  (`GET /duplicados`) y la razón «Posible duplicado» en la búsqueda por foto.

**Caché de búsquedas** (`servicio/fototeca/cache/cache_busquedas.py`): exacta por texto normalizado + filtros +
`version_archivo` + versión de configuración, y semántica por el vector del texto con τ_busq (inicial 0.95); TTL de 24 h.

**Invalidación:** cada ficha en caché lleva las etiquetas `doc:<id>` (la foto y los vecinos usados como fuente),
`corpus:<versión>` y `config:<versión>`. `DELETE /documentos/{id}` y la validación de una ficha invalidan `doc:<id>`; un
cambio del corpus o de la configuración cambia la versión, y las entradas viejas dejan de encontrarse. Las búsquedas
dependen de `version_archivo`, que sube con cada ingesta, eliminación o validación. Todo vive en SQLite, con búsqueda
lineal en numpy sobre los vectores guardados (ADR-09).

## Alternativas
- **Solo caché exacta:** no reconoce una foto recortada o recomprimida (sus bytes cambian), que es justo el caso de los
  archivos reales.
- **Un umbral más bajo (por ejemplo, 0.90):** más aciertos, pero más riesgo de servir la ficha de otra foto del mismo
  lugar; el barrido decide.
- **TTL también para las fichas validadas:** se perdería el trabajo del archivista sin razón; se invalidan cuando se
  elimina el documento.
- **Redis o una colección de Qdrant para la caché:** más memoria o más acoplamiento, sin ganancia clara para el tamaño
  de caché de una demo (ADR-09).

## Evidencia
Fuente: `evaluacion/resultados/cache.json` (corrida del 2026-11-13 con `--fraccion 0.5`: 150 transformaciones
positivas de `casi_duplicados_pos`, 75 pares negativos de `casi_duplicados_neg`, 25 cargas idénticas y 15 pares de
búsquedas; gráficas en `evaluacion/graficas/cache_tau_dup.png` y `cache_latencia.png`). La regla de elección se fijó antes de medir: **máximo recall con una
tasa de falsos positivos de 2 % o menos** (empates: menor FPR y luego τ más alto).

**Barrido de τ_dup** (`metricas.fichas_semantica_tau_dup.barrido`; un falso positivo es la ficha de otra foto servida
desde la caché):

| τ_dup | Recall | FPR (negativos) | Precisión |
|---|---|---|---|
| 0.90 | 0.9933 | 0.0533 | 0.9739 |
| 0.93 | 0.9867 | 0.0533 | 0.9737 |
| 0.94 | 0.96 | 0.04 | 0.9796 |
| **0.95 (elegido)** | **0.94** | **0.0133** | **0.993** |
| 0.96 | 0.86 | 0.0133 | 0.9923 |
| 0.97 (valor inicial) | 0.7067 | 0.0133 | 0.9907 |
| 0.98 | 0.48 | 0.0 | 1.0 |

- **τ_dup = 0.95:** es el τ más bajo con FPR ≤ 2 %. Reconoce 141 de 150 transformaciones contra 106 de 150 con el
  valor inicial (0.97), con la misma tasa de falsos positivos (1 de 75 pares negativos). Ninguna transformación tuvo como
  vecino más cercano otra foto (`positivos_cuyo_vecino_mas_cercano_no_es_el_original` = 0).
- **Por transformación**, recall con τ = 0.95 contra 0.97: recorte 0.7917 contra 0.4167, marco de captura 0.9474
  contra 0.5263, rotación 0.9677 contra 0.6774, recompresión 0.9524 contra 0.7143, espejo 0.9667 contra 0.8333 y
  brillo y saturación 1.0 en los dos. El recorte es la transformación más difícil (similitud p50 con su original de
  0.9684).
- **Caché exacta** (`fichas_exacta`): 25 de 25 cargas repetidas respondieron desde la caché exacta, con la misma ficha y
  el mismo documento. Latencia del cliente: p50 de 69.312 s sin caché contra 0.023 s con caché (reducción del 99.97 %);
  en el servidor, 14.3 ms. Cumple la meta de p50 ≤ 0.5 s (`metas.ficha_cache_p50_s`).
- **Búsquedas** (`busquedas`): 15 de 15 búsquedas repetidas acertaron en la caché exacta (p50 de 0.225 s contra 0.454 s
  sin caché). Las 15 paráfrasis no acertaron en la semántica: su similitud con la consulta original llegó como máximo a
  0.907, por debajo de τ_busq = 0.95. No se sirvió ninguna respuesta incorrecta (0 de 15).
- **Invalidación** (`invalidacion`): al eliminar por la API una foto con ficha en caché se invalidó 1 entrada; la
  exacta, la semántica y la búsqueda en caché dejaron de responder, y la nueva ficha de la misma foto se generó desde
  cero (`aprobada: true`).

**Lectura.** Subir τ_dup de 0.95 a 0.97 no reduce los falsos positivos (el único par negativo servido tiene similitud
de 0.97 o más) y sí deja sin reconocer 35 transformaciones más (106 contra 141 de 150); bajarlo a 0.94 triplica la FPR (3 de 75). La caché
semántica de búsquedas, con τ_busq = 0.95, no atrapa paráfrasis en español: solo sirve para repeticiones casi exactas.
Se conserva así porque no sirve respuestas incorrectas; calibrar τ_busq exige pares de consultas distintas que hoy no
están en los conjuntos.

## Consecuencias
- **Se gana:** una foto repetida o casi repetida se responde sin llamar a ningún modelo de lenguaje, y el archivista
  recibe de paso el aviso de duplicado. La invalidación por etiquetas evita servir fichas que dependían de un documento
  eliminado o de una configuración vieja.
- **Se sacrifica:** con τ_dup = 0.95 todavía 1 de cada 5 recortes no se reconoce y paga la ficha completa; la caché
  semántica de búsquedas casi no acierta.
- **Riesgos:** con τ_dup = 0.95 la FPR medida es 0.0133 (1 de 75), dentro de la meta de 2 %
  (`servicio/config/metas_calidad.yaml`), pero sobre solo 75 negativos; la corrida completa duplica la muestra. Un
  acierto semántico siempre llega con el aviso «Posible duplicado de …» para que el archivista lo confirme. La búsqueda lineal en SQLite es
  suficiente para una caché pequeña; si la caché crece mucho, habría que medir su costo.
