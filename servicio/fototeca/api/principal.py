"""Punto de entrada de uvicorn: `uvicorn fototeca.api.principal:app`."""
from fototeca.api.arranque import crear_app

app = crear_app()
