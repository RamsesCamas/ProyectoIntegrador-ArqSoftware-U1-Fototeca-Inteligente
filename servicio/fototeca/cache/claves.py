"""Claves de la caché exacta (C4; ADR-04)."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata


def normalizar_texto(texto: str) -> str:
    """Minúsculas, sin signos de puntuación y con espacios simples (conserva acentos: «año» ≠ «ano»)."""
    texto = unicodedata.normalize("NFC", texto or "").lower()
    texto = re.sub(r"[^\w\s]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def clave_ficha(sha256_imagen: str, version_configuracion: str) -> str:
    return f"ficha:{sha256_imagen}:{version_configuracion}"


def clave_busqueda(texto: str, filtros: dict | None, version_archivo: int, version_configuracion: str) -> str:
    cuerpo = json.dumps({"t": normalizar_texto(texto), "f": filtros or {}, "a": version_archivo,
                         "c": version_configuracion}, sort_keys=True, ensure_ascii=False)
    return "busqueda:" + hashlib.sha256(cuerpo.encode("utf-8")).hexdigest()[:32]
