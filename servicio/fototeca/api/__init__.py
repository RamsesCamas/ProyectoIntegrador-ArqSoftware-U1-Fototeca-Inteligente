"""C1 · Interfaz del servicio (API REST con FastAPI).

Recibe las peticiones HTTP, valida entrada y salida con Pydantic y traduce cada petición en una llamada a la
capa de orquestación. No contiene lógica de IA. `arranque.py` es la raíz de composición: el único lugar que
conoce los adaptadores concretos de C7 y los conecta con los puertos.
"""
