"""R6 · Contrato de capas con import-linter.

1. El código real cumple los contratos de `pyproject.toml`.
2. Prueba negativa automática: en una copia del paquete se agrega un import indebido (C7 → C1) y el contrato
   debe fallar. Así se demuestra que el contrato «tiene dientes» sin tocar el código real.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _lint(directorio: Path) -> subprocess.CompletedProcess:
    entorno = {**os.environ, "PYTHONPATH": str(directorio)}
    lint = shutil.which("lint-imports") or str(Path(sys.executable).parent / "lint-imports")
    return subprocess.run([lint, "--config", str(directorio / "pyproject.toml")], cwd=directorio,
                          env=entorno, capture_output=True, text=True, timeout=120)


def test_contrato_de_capas_se_cumple():
    r = _lint(RAIZ)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Contracts: 3 kept, 0 broken" in r.stdout


def test_contrato_detecta_import_indebido(tmp_path):
    shutil.copytree(RAIZ / "fototeca", tmp_path / "fototeca",
                    ignore=shutil.ignore_patterns("__pycache__", "estaticos"))
    shutil.copy(RAIZ / "pyproject.toml", tmp_path / "pyproject.toml")
    infractor = tmp_path / "fototeca" / "datos" / "infractor.py"
    infractor.write_text("import fototeca.api.arranque  # C7 → C1: prohibido\n", encoding="utf-8")
    r = _lint(tmp_path)
    assert r.returncode != 0
    assert "broken" in r.stdout


def test_transversal_no_puede_importar_negocio(tmp_path):
    shutil.copytree(RAIZ / "fototeca", tmp_path / "fototeca",
                    ignore=shutil.ignore_patterns("__pycache__", "estaticos"))
    shutil.copy(RAIZ / "pyproject.toml", tmp_path / "pyproject.toml")
    (tmp_path / "fototeca" / "observabilidad" / "infractor.py").write_text(
        "import fototeca.datos.puertos  # T1 → C7: prohibido\n", encoding="utf-8")
    r = _lint(tmp_path)
    assert r.returncode != 0
    assert "Transversales independientes BROKEN" in r.stdout
