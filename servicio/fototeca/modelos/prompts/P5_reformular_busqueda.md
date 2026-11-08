---
version: 1
tarea: P5
nombre: reformular_busqueda
modelo_preferido: composicion
modelo_respaldo: vision
num_predict: 150
temperatura: 0.0
con_imagen: false
---
## Sistema
Reformulas búsquedas para un archivo fotográfico. Responde solo JSON.

## Usuario
La búsqueda "{consulta}" no encontró fotos relevantes. Propón 3 reformulaciones distintas y más concretas (sinónimos, términos más generales o descripciones visuales). Responde solo JSON: {"reformulaciones": [..3..]}

## Esquema
```json
{"type":"object","required":["reformulaciones"],
 "properties":{"reformulaciones":{"type":"array","items":{"type":"string","maxLength":160},"minItems":1,"maxItems":3}}}
```
