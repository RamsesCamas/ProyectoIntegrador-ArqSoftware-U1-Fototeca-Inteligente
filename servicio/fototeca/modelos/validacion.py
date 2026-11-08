"""Validación mínima de JSON Schema para las salidas de los modelos (type, required, properties, enum, items,
minItems, maxItems, maxLength, additionalProperties) y extracción del JSON de una respuesta."""
from __future__ import annotations

import json
import re

_THINK = re.compile(r"<think>.*?</think>", re.S)
_TIPOS = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int, "number": (int, float),
          "null": type(None)}


def validar(obj, esquema: dict, ruta: str = "$") -> list[str]:
    errores: list[str] = []
    if "enum" in esquema and obj not in esquema["enum"]:
        errores.append(f"{ruta}: {obj!r} no es uno de {esquema['enum']}")
    tipo = esquema.get("type")
    if isinstance(tipo, list):
        if not any(isinstance(obj, _TIPOS[t]) and not (t in ("integer", "number") and isinstance(obj, bool))
                   for t in tipo):
            errores.append(f"{ruta}: tipo inválido, se esperaba {tipo}")
        return errores
    if tipo == "object":
        if not isinstance(obj, dict):
            return errores + [f"{ruta}: se esperaba un objeto"]
        for k in esquema.get("required", []):
            if k not in obj:
                errores.append(f"{ruta}: falta el campo «{k}»")
        props, extra = esquema.get("properties", {}), esquema.get("additionalProperties")
        for k, v in obj.items():
            if k in props:
                errores += validar(v, props[k], f"{ruta}.{k}")
            elif isinstance(extra, dict):
                errores += validar(v, extra, f"{ruta}.{k}")
    elif tipo == "array":
        if not isinstance(obj, list):
            return errores + [f"{ruta}: se esperaba una lista"]
        if len(obj) > esquema.get("maxItems", 10**9):
            errores.append(f"{ruta}: {len(obj)} elementos (máximo {esquema['maxItems']})")
        if len(obj) < esquema.get("minItems", 0):
            errores.append(f"{ruta}: {len(obj)} elementos (mínimo {esquema['minItems']})")
        for i, x in enumerate(obj):
            errores += validar(x, esquema.get("items", {}), f"{ruta}[{i}]")
    elif tipo == "string":
        if not isinstance(obj, str):
            errores.append(f"{ruta}: se esperaba texto")
        elif len(obj) > esquema.get("maxLength", 10**9):
            errores.append(f"{ruta}: {len(obj)} caracteres (máximo {esquema['maxLength']})")
    elif tipo == "boolean" and not isinstance(obj, bool):
        errores.append(f"{ruta}: se esperaba verdadero o falso")
    return errores


def extraer_json(texto: str) -> tuple[dict | None, list[str]]:
    """Quita bloques <think>, busca el objeto JSON y lo decodifica."""
    limpio = _THINK.sub("", texto or "").strip()
    if limpio.startswith("```"):
        limpio = re.sub(r"^```(?:json)?\s*|\s*```$", "", limpio)
    try:
        return json.loads(limpio), []
    except json.JSONDecodeError:
        inicio, fin = limpio.find("{"), limpio.rfind("}")
        if 0 <= inicio < fin:
            try:
                return json.loads(limpio[inicio:fin + 1]), []
            except json.JSONDecodeError as e:
                return None, [f"JSON inválido: {e.msg}"]
        return None, ["La respuesta no contiene un objeto JSON"]
