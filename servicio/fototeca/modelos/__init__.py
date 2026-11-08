"""C6 · Enrutador y gateway de modelos.

El enrutador elige la ruta (rápida o completa para fichas; simple, compleja o imagen para búsquedas) con un
criterio explícito. El gateway es la interfaz única hacia los modelos: tiempo límite, reintentos, cadena de
respaldo y registro de uso (docs/specs/05-modelos-gateway-enrutador.md).
"""
