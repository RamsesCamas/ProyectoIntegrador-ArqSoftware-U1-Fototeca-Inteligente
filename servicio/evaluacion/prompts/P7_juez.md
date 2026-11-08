---
version: 1
tarea: P7
nombre: juez_evaluacion
modelo_preferido: composicion
modelo_respaldo: null
num_predict: 120
temperatura: 0.0
con_imagen: false
# Solo se usa en evaluacion/ (docs/specs/07, P7). Nunca forma parte del servicio en producción.
---
## Sistema
Evalúas fichas de catálogo fotográfico. Responde solo JSON.

## Usuario
Evalúas una ficha generada contra descripciones de referencia escritas por personas para la MISMA foto.
Califica de 0 a 5:
- "fidelidad": ¿lo que dice la ficha es compatible con las referencias? (5 = nada contradictorio ni inventado)
- "relevancia": ¿el texto alternativo captura lo esencial que mencionan las referencias? (5 = todo lo esencial)
Justifica en una oración. Responde solo JSON {"fidelidad": int, "relevancia": int, "justificacion": str}.
REFERENCIAS: {referencias}
FICHA: titular={titular} | texto_alternativo={texto_alternativo} | descripcion={descripcion}

## Esquema
```json
{"type":"object","required":["fidelidad","relevancia","justificacion"],
 "properties":{"fidelidad":{"type":"integer","enum":[0,1,2,3,4,5]},"relevancia":{"type":"integer","enum":[0,1,2,3,4,5]},
  "justificacion":{"type":"string","maxLength":240}}}
```
