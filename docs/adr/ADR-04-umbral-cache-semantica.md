# ADR-04: Umbral de la caché semántica τ_dup, su TTL e invalidación por etiquetas

**Estado:** Propuesta
**Fecha:** 2026-11-08
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
- **Semántica:** vector de la imagen en EmbeddingGemma-2 contra el umbral **τ_dup** (valor inicial 0.97 en
  `servicio/config/parametros.yaml`, `cache.fichas.tau_dup`), en dos niveles: (1) fichas generadas antes por el
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
**pendiente:** `evaluacion/resultados/cache.json` (curvas en `evaluacion/graficas/cache_*.png`):
- barrido de τ_dup de 0.90 a 0.99 en pasos de 0.01 sobre `casi_duplicados_pos` (300 transformaciones de 150 fotos) y
  `casi_duplicados_neg` (el vecino más cercano distinto de cada una): tasa de aciertos, respuestas incorrectas servidas
  desde la caché y curva de precisión y recall. Regla de elección, fijada antes de medir: **máximo recall con una tasa
  de falsos positivos de 2 % o menos**;
- 50 cargas idénticas (caché exacta) y 30 búsquedas repetidas y 30 parafraseadas;
- latencia con y sin caché (p50 y reducción porcentual);
- la prueba automática de invalidación: se elimina un documento y su entrada ya no responde.

## Consecuencias
- **Se gana:** una foto repetida o casi repetida se responde sin llamar a ningún modelo de lenguaje, y el archivista
  recibe de paso el aviso de duplicado. La invalidación por etiquetas evita servir fichas que dependían de un documento
  eliminado o de una configuración vieja.
- **Se sacrifica:** con τ_dup alto, algunas transformaciones fuertes (recortes grandes, marcos de captura) no se
  reconocen y pagan la ficha completa.
- **Riesgos:** si el umbral elegido queda bajo, dos fotos distintas pueden compartir ficha; la métrica de respuestas
  incorrectas lo vigila y la meta es 2 % o menos (`servicio/config/metas_calidad.yaml`). La búsqueda lineal en SQLite es
  suficiente para una caché pequeña; si la caché crece mucho, habría que medir su costo.
