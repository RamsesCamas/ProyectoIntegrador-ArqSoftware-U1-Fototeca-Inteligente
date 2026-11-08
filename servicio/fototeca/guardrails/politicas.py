"""Políticas ante cada falla de guardrail (C3; ADR-05).

Cada verificación declara aquí qué se hace cuando falla. El flujo (C2) consulta esta tabla en lugar de decidir
por su cuenta, para que la política sea explícita, única y documentable.
"""
from __future__ import annotations

from typing import Literal

Politica = Literal["bloquear", "sanitizar", "marcar", "reintentar", "aislar"]

POLITICAS: dict[str, tuple[Politica, str]] = {
    # Entrada (fotos)
    "archivo_valido": ("bloquear", "Archivo inválido: se rechaza con 413, 415 o 422 y un mensaje seguro"),
    "exif_privacidad": ("sanitizar", "Se quitan GPS, número de serie y autor antes de guardar; queda en la traza"),
    "fuera_de_dominio": ("bloquear", "No parece una fotografía: se rechaza con 422 y un mensaje seguro"),
    "inyeccion_en_imagen": ("aislar", "No se bloquea: el texto visible pasa como dato citado, se agrega una "
                                      "advertencia y la ficha queda en revisión si la confianza es alta"),
    # Entrada (texto de búsqueda)
    "pii_texto": ("sanitizar", "Se enmascaran CURP, RFC, correo, teléfono y tarjeta y se continúa"),
    "inyeccion_texto": ("bloquear", "Se rechaza con 422 y un mensaje seguro, sin repetir el contenido"),
    # Salida (ficha)
    "esquema": ("reintentar", "Un reintento con el error del validador; después, la cadena de respaldo"),
    "reglas_iptc": ("sanitizar", "Recortar por oración y normalizar el inicio; si queda vacío, reintentar"),
    "apego_visual": ("reintentar", "Reintentar por la ruta completa si venía de la rápida; si vuelve a fallar, marcar"),
    "consistencia": ("marcar", "La ficha queda en revisión"),
    "atributos_sensibles": ("reintentar", "Eliminar la frase, reintentar una vez y luego marcar"),
    "tesauro": ("sanitizar", "Cada palabra clave se normaliza al concepto más cercano o queda como término libre"),
    "fuentes": ("sanitizar", "Se quitan las fuentes inválidas; si un campo queda sin fuentes, se marca"),
    # Salida (búsquedas)
    "salida_busqueda": ("sanitizar", "No se exponen rutas internas, EXIF ni GPS; siempre va el aviso de IA"),
}

MENSAJES_SEGUROS = {
    "archivo_valido": "El archivo no es una foto JPEG o PNG válida dentro de los límites permitidos.",
    "fuera_de_dominio": "Esto no parece una fotografía: parece un documento, una tabla o una captura de pantalla. "
                        "Fototeca Viva cataloga fotografías.",
    "inyeccion_texto": "La búsqueda contiene instrucciones que no corresponden a una descripción de fotos y no se "
                       "procesó. Describe lo que quieres ver en las fotos.",
}


def politica(verificacion: str) -> Politica:
    return POLITICAS[verificacion][0]
