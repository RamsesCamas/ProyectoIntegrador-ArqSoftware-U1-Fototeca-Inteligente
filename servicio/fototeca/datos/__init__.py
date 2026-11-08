"""C7 · Acceso a datos y modelos: puertos (`Protocol`) y un adaptador por recurso.

Las capas superiores dependen solo de `datos.puertos`. Cambiar Qdrant por otra base vectorial, u Ollama por
otro servidor de modelos, significa agregar un adaptador aquí y conectarlo en la raíz de composición.
"""
