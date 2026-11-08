"""R8 · La web solo consume la API por HTTP: no puede referirse al servidor de modelos ni a la base vectorial.

docs/specs/10-web.md: el test busca en web/ cualquier referencia a 11434, 6333, ollama o qdrant.
La carpeta web/ se monta de solo lectura en el contenedor `servicio` (docker-compose.yml).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

WEB = Path(os.environ.get("FOTOTECA_WEB", "/app/web_estatica"))
PROHIBIDO = re.compile(r"11434|6333|ollama|qdrant", re.IGNORECASE)


@pytest.fixture(scope="module")
def archivos_web():
    if not WEB.is_dir():
        pytest.skip(f"No está montada la carpeta web en {WEB}")
    archivos = [p for p in WEB.rglob("*") if p.is_file() and p.suffix in (".html", ".js", ".css", ".conf", ".json")]
    assert archivos, "la carpeta web está vacía"
    return archivos


def test_web_no_menciona_modelos_ni_base_vectorial(archivos_web):
    hallazgos = []
    for ruta in archivos_web:
        if ruta.name == "nginx.conf":
            continue  # el proxy solo apunta a servicio:8000; se revisa aparte
        for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
            if PROHIBIDO.search(linea):
                hallazgos.append(f"{ruta.relative_to(WEB)}:{n}: {linea.strip()[:100]}")
    assert not hallazgos, "\n".join(hallazgos)


def test_proxy_solo_hacia_el_servicio(archivos_web):
    conf = (WEB / "nginx.conf").read_text(encoding="utf-8")
    assert not PROHIBIDO.search(conf)
    assert set(re.findall(r"http://([\w.-]+):\d+", conf)) == {"servicio"}


def test_fetch_solo_a_la_api(archivos_web):
    for ruta in archivos_web:
        if ruta.suffix != ".js":
            continue
        texto = ruta.read_text(encoding="utf-8")
        for url in re.findall(r"fetch\(\s*[`'\"]([^`'\"]+)", texto):
            assert url.startswith("/api"), f"{ruta.name}: fetch a {url}"
        assert "http://" not in texto and "https://" not in texto, f"{ruta.name} usa una URL absoluta"
