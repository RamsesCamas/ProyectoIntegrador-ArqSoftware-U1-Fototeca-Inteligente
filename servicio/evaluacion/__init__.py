"""Evaluación del sistema (informe, §10): R3 (selección de modelos) y R9 (calidad por capa).

Cada módulo lee su conjunto de `evaluacion/conjuntos/`, llama al servicio a través de la API (TestClient en el
mismo proceso, con MODO_EVALUACION activo SOLO aquí), guarda resultados incrementales y reanudables y escribe
`evaluacion/resultados/<modulo>.json`, `<modulo>_detalle.csv` y `evaluacion/graficas/<modulo>_*.png`.
"""
