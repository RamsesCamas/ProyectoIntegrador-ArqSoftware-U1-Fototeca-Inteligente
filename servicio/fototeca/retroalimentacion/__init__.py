"""T2 · Retroalimentación del usuario (transversal): opinión ligada a la traza y promoción de fichas validadas.

Define el puerto `AlmacenRetroalimentacion`; el adaptador SQLite vive en C7
(`datos/retroalimentacion_sqlite.py`). T2 solo persiste y emite el evento; la promoción de una ficha validada
como ejemplo del RAG la orquesta C2 (`orquestacion/retroalimentacion.py`), para que T2 no dependa de ninguna
capa de negocio.
"""
