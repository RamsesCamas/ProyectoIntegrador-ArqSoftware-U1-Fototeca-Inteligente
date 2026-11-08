"""C2 · Orquestación y patrones de agente.

Coordina el flujo de cada consulta a través de las capas inferiores con una máquina de estados explícita
(ficha, búsqueda, ingesta, lotes) e implementa el ciclo de agente: si la recuperación es pobre, reformula
(ruta pipeline) y vuelve a buscar, con un máximo de iteraciones (docs/specs/06-capas-detalle.md, C2).
"""
