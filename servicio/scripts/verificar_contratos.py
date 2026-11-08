"""Evidencia del contrato de capas (R6, ADR-13): import-linter sobre el código real y sobre dos copias con un import
prohibido cada una, que el contrato debe rechazar.

    python -m scripts.verificar_contratos

1. Código real → los 3 contratos de `pyproject.toml` se cumplen.
2. Copia con `fototeca/datos/infractor.py` que importa `fototeca.api.arranque` (C7 → C1) → contrato de capas roto.
3. Copia con `fototeca/observabilidad/infractor.py` que importa `fototeca.datos.puertos` (T1 → C7) → contrato de
   transversales roto.
Escribe `evaluacion/resultados/contrato_capas.json` con la salida textual de cada corrida.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts._descargas import EVAL, ahora_iso, json_guardar, registro

RAIZ = Path(__file__).resolve().parents[1]
INFRACTORES = {
    "c7_importa_c1": ("datos", "import fototeca.api.arranque  # C7 → C1: prohibido\n"),
    "t1_importa_c7": ("observabilidad", "import fototeca.datos.puertos  # T1 → C7: prohibido\n"),
}


def _lint(directorio: Path) -> dict:
    lint = shutil.which("lint-imports") or str(Path(sys.executable).parent / "lint-imports")
    r = subprocess.run([lint, "--config", str(directorio / "pyproject.toml")], cwd=directorio,
                       env={**os.environ, "PYTHONPATH": str(directorio)}, capture_output=True, text=True, timeout=180)
    salida = r.stdout.strip().splitlines()
    return {"codigo_salida": r.returncode, "resumen": next((l for l in salida if l.startswith("Contracts:")), None),
            "rotos": [l.replace(" BROKEN", "") for l in salida if l.endswith("BROKEN")],
            "salida": "\n".join(salida[-25:])}


def main() -> None:
    resultado = {"fecha": ahora_iso(), "configuracion": "servicio/pyproject.toml [tool.importlinter]",
                 "codigo_real": _lint(RAIZ), "pruebas_negativas": {}}
    for nombre, (paquete, linea) in INFRACTORES.items():
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp)
            shutil.copytree(RAIZ / "fototeca", destino / "fototeca", ignore=shutil.ignore_patterns("__pycache__", "estaticos"))
            shutil.copy(RAIZ / "pyproject.toml", destino / "pyproject.toml")
            (destino / "fototeca" / paquete / "infractor.py").write_text(linea, encoding="utf-8")
            resultado["pruebas_negativas"][nombre] = {"import_agregado": linea.strip(), **_lint(destino)}
    resultado["ok"] = (resultado["codigo_real"]["codigo_salida"] == 0
                       and all(x["codigo_salida"] != 0 for x in resultado["pruebas_negativas"].values()))
    json_guardar(EVAL / "resultados" / "contrato_capas.json", resultado)
    registro(f"contrato: real → {resultado['codigo_real']['resumen']} · negativas → "
             + ", ".join(f"{k}: {v['resumen']}" for k, v in resultado["pruebas_negativas"].items()))


if __name__ == "__main__":
    main()
