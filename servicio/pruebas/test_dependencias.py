"""Regla 9 de CLAUDE.md: dependencias fijadas con == y requirements.txt coherente con el lock de uv."""
from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def test_dependencias_directas_con_igual_igual():
    proyecto = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    directas = proyecto["project"]["dependencies"] + proyecto["dependency-groups"]["dev"]
    sin_fijar = [d for d in directas if "==" not in d]
    assert not sin_fijar, sin_fijar


def test_requirements_todo_fijado():
    lineas = [l.strip() for l in (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines()]
    paquetes = [l for l in lineas if l and not l.startswith("#")]
    assert paquetes, "requirements.txt vacío"
    assert all(re.match(r"^[A-Za-z0-9_.\-\[\]]+==[^=\s]+", p) for p in paquetes), paquetes


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv no está en el PATH")
def test_requirements_coincide_con_uv_lock():
    r = subprocess.run(["uv", "export", "--frozen", "--no-hashes", "--no-emit-project", "--format",
                        "requirements-txt"], cwd=RAIZ, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    exportado = {l.strip() for l in r.stdout.splitlines() if l.strip() and not l.strip().startswith("#")}
    actual = {l.strip() for l in (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines()
              if l.strip() and not l.strip().startswith("#")}
    assert exportado == actual, "Regenera requirements.txt con `uv export` (ver Dockerfile)"
