"""T2 · Retroalimentación del usuario (transversal): opinión ligada a la traza y promoción de fichas validadas.

Define el puerto `AlmacenRetroalimentacion`; el adaptador SQLite vive en C7
(`datos/retroalimentacion_sqlite.py`). T2 solo persiste y emite el evento; la promoción de una ficha validada
como ejemplo del RAG la orquesta C2 (docs/specs/06-capas-detalle.md, T2).
"""
