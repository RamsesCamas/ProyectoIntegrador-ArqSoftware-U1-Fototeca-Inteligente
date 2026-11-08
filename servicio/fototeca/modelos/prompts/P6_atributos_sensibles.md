---
version: 1
tarea: P6
nombre: verificar_atributos_sensibles
modelo_preferido: vision
modelo_respaldo: null
num_predict: 80
temperatura: 0.0
con_imagen: false
---
## Sistema
Revisas textos de catálogo para detectar atributos sensibles. Responde solo JSON.

## Usuario
¿El siguiente texto atribuye a alguna persona etnia, raza, religión, orientación sexual, discapacidad, condición de salud o la identifica por nombre? Responde solo JSON {"sensible": bool, "fragmentos": [..]}.
TEXTO: {campo}

## Esquema
```json
{"type":"object","required":["sensible","fragmentos"],
 "properties":{"sensible":{"type":"boolean"},"fragmentos":{"type":"array","items":{"type":"string"},"maxItems":5}}}
```
