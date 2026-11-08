"""T1 · Observabilidad (transversal): traza por consulta, bitácora JSON por capa y métricas.

Define el puerto `SumideroEventos`; el adaptador SQLite concreto vive en C7 (`datos/eventos_sqlite.py`) y la
raíz de composición (`api/arranque.py`) los conecta. Así T1 no importa ninguna capa de negocio.
"""
