"""Licencias de los paquetes de Python instalados en la imagen `servicio` (para docs/LICENCIAS-Y-CORPUS.md).

    python -m scripts.licencias_paquetes

Lee los metadatos de cada distribución instalada en el entorno (`importlib.metadata`): `License-Expression`
(PEP 639), si no `License`, y si no los clasificadores «License ::». Escribe
`evaluacion/resultados/licencias_paquetes.json` e imprime la tabla en Markdown.
"""
from __future__ import annotations

import json
import re
from importlib import metadata

from scripts._descargas import EVAL, ahora_iso, json_guardar


def licencia(dist: metadata.Distribution) -> tuple[str, str]:
    m = dist.metadata
    expresion = (m.get("License-Expression") or "").strip()
    if expresion:
        return expresion, "License-Expression"
    texto = (m.get("License") or "").strip()
    if texto and len(texto) <= 60 and "\n" not in texto:
        return texto, "License"
    clasificadores = [c.split("::")[-1].strip() for c in (m.get_all("Classifier") or []) if c.startswith("License ::")]
    if clasificadores:
        return "; ".join(dict.fromkeys(clasificadores)), "Classifier"
    if texto:
        primera = re.split(r"[\r\n]", texto)[0].strip()
        return (primera[:60] + "…") if len(primera) > 60 else primera, "License (primera línea)"
    return "sin dato en los metadatos", "—"


def main() -> None:
    filas = []
    for dist in sorted(metadata.distributions(), key=lambda d: (d.metadata["Name"] or "").lower()):
        nombre = dist.metadata["Name"]
        if not nombre:
            continue
        lic, campo = licencia(dist)
        filas.append({"paquete": nombre, "version": dist.version, "licencia": lic, "campo": campo})
    vistos, unicas = set(), []
    for f in filas:
        if f["paquete"].lower() not in vistos:
            vistos.add(f["paquete"].lower())
            unicas.append(f)
    json_guardar(EVAL / "resultados" / "licencias_paquetes.json", {"fecha": ahora_iso(), "paquetes": unicas})
    print("| Paquete | Versión | Licencia (metadatos) |")
    print("|---|---|---|")
    for f in unicas:
        print(f"| {f['paquete']} | {f['version']} | {f['licencia']} |")


if __name__ == "__main__":
    main()
