"""Guardrails de entrada para el texto de búsqueda (docs/specs/06, C3):

- `pii_texto`: CURP, RFC, correo, teléfono y tarjeta con expresiones regulares → sanitizar (enmascarar) y seguir.
- `inyeccion_texto`: heurística de patrones + similitud con los prototipos de inyección → bloquear con mensaje
  seguro (422), sin repetir el contenido malicioso.
"""
from __future__ import annotations

import re

import numpy as np

from fototeca.dominio.errores import BloqueadoPorGuardrail
from fototeca.guardrails.politicas import MENSAJES_SEGUROS, politica
from fototeca.guardrails.resultado import ResultadoGuardrail

PATRONES_PII = {
    "curp": re.compile(r"\b[A-Z][AEIOUX][A-Z]{2}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b", re.I),
    "rfc": re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b", re.I),
    "correo": re.compile(r"\b[\w.+-]+@[\w-]+(\.[\w-]+)+\b"),
    "tarjeta": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    "telefono": re.compile(r"(?<!\d)(?:\+?52[ -]?)?(?:\(?\d{2,3}\)?[ -]?)\d{3,4}[ -]?\d{4}(?!\d)"),
}
ETIQUETA = {"curp": "[CURP]", "rfc": "[RFC]", "correo": "[CORREO]", "tarjeta": "[TARJETA]", "telefono": "[TELÉFONO]"}

PATRONES_INYECCION = [
    r"\bignora(r|d)?\b.*\b(instruc|regla|anterior|lo anterior)", r"\bolvida(r)?\b.*\b(instruc|regla|todo)",
    r"\bignore\b.*\b(instruction|rule|previous)", r"\bforget\b.*\b(rule|instruction)", r"\bdisregard\b",
    r"^\s*(system|assistant|sistema)\s*:", r"#{2,}\s*(system|instrucci)", r"\b(prompt|configuraci[oó]n)\s+(de\s+)?(sistema|interna|oculta)",
    r"\bsystem prompt\b", r"\b(modo|mode)\s+(desarrollador|developer)\b", r"\beres ahora\b|\bahora eres\b|\byou are now\b",
    r"\bact[uú]a como\b|\bact as\b", r"\b(revela|muestra|imprime|devuelve|reveal|print|output)\b.*\b(gps|coordenadas|rutas|datos personales|base de datos|configuraci|prompt)",
    r"\b(borra|elimina|delete)\b.*\b(fichas|base de datos|registros|records|todo)", r"\bdesactiva\b.*\b(filtro|guardrail|seguridad)",
    r"\bjailbreak\b|\bDAN\b", r"\bnueva instrucci[oó]n\b|\bnew instructions?\b",
]
_INYECCION = [re.compile(p, re.I) for p in PATRONES_INYECCION]


def _luhn(digitos: str) -> bool:
    n = [int(c) for c in digitos][::-1]
    return len(n) >= 13 and sum(d if i % 2 == 0 else (d * 2 - 9 if d * 2 > 9 else d * 2) for i, d in enumerate(n)) % 10 == 0


def sanitizar_pii(texto: str) -> tuple[str, ResultadoGuardrail]:
    encontrados: list[str] = []
    limpio = texto
    for clase, patron in PATRONES_PII.items():
        def reemplazo(m, clase=clase):
            if clase == "tarjeta" and not _luhn(re.sub(r"\D", "", m.group(0))):
                return m.group(0)
            encontrados.append(clase)
            return ETIQUETA[clase]
        limpio = patron.sub(reemplazo, limpio)
    if encontrados:
        return limpio, ResultadoGuardrail("pii_texto", "sanitizado", politica_aplicada=politica("pii_texto"),
                                          detalle={"enmascarado": sorted(set(encontrados))})
    return texto, ResultadoGuardrail("pii_texto", "aprobada")


def verificar_inyeccion(texto: str, vector_simetrico: np.ndarray | None, prototipos: np.ndarray | None,
                        umbral: float) -> ResultadoGuardrail:
    """Bloquea si coincide un patrón heurístico o si la similitud con los prototipos de inyección supera el umbral."""
    patrones = [p.pattern for p in _INYECCION if p.search(texto)]
    similitud = None
    if vector_simetrico is not None and prototipos is not None and len(prototipos):
        similitud = float(np.max(prototipos @ vector_simetrico))
    por_similitud = similitud is not None and similitud >= umbral
    if patrones or por_similitud:
        r = ResultadoGuardrail("inyeccion_texto", "bloqueada", valor=None if similitud is None else round(similitud, 4),
                               umbral=umbral, politica_aplicada=politica("inyeccion_texto"),
                               detalle={"patrones": len(patrones), "por_similitud": por_similitud})
        raise BloqueadoPorGuardrail(MENSAJES_SEGUROS["inyeccion_texto"], [r.a_dict()])
    return ResultadoGuardrail("inyeccion_texto", "aprobada", valor=None if similitud is None else round(similitud, 4),
                              umbral=umbral)
