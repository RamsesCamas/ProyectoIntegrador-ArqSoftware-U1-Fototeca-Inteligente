"""Fixtures de las pruebas E2E: Chromium con la API síncrona de Playwright, la URL de la web y la foto de prueba.

Variables de entorno (todas opcionales):
- FOTOTECA_WEB_URL: dónde está la web (por defecto http://web, el servicio `web` de la misma red de compose).
- FOTOTECA_E2E_FOTO: foto de prueba (ruta dentro del contenedor). Por defecto, la primera de /datos/demo/ o la
  primera de la partición `nuevas` (fotos que NO están en el archivo de referencia).
- FOTOTECA_E2E_ESPERA_FICHA_S: espera máxima de una ficha (300 s, como el proxy de la web).
- FOTOTECA_E2E_ESPERA_SALUD_S: espera máxima a que el sistema esté listo (600 s: precalentamiento de modelos).
"""
from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Page, sync_playwright

URL_WEB = os.environ.get("FOTOTECA_WEB_URL", "http://web").rstrip("/")
DATOS = Path(os.environ.get("FOTOTECA_DATOS", "/datos"))
EVALUACION = Path(os.environ.get("FOTOTECA_EVALUACION", "/evaluacion"))
ESPERA_FICHA_MS = int(float(os.environ.get("FOTOTECA_E2E_ESPERA_FICHA_S", "300")) * 1000)
ESPERA_SALUD_S = float(os.environ.get("FOTOTECA_E2E_ESPERA_SALUD_S", "600"))
EXTENSIONES = (".jpg", ".jpeg", ".png")


# ───────────────────────────── API (solo para preparar y limpiar) ─────────────────────────────
def pedir(metodo: str, ruta: str, cuerpo: bytes | None = None, tipo: str | None = None) -> tuple[int, dict]:
    """Petición a la API a través del proxy de la web (`/api/*`), igual que el navegador."""
    peticion = urllib.request.Request(f"{URL_WEB}/api{ruta}", data=cuerpo, method=metodo,
                                      headers={"Accept": "application/json", **({"Content-Type": tipo} if tipo else {})})
    try:
        with urllib.request.urlopen(peticion, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def subir_foto(ruta: Path) -> dict:
    """POST /api/documentos (multipart) con una foto; devuelve el resultado del documento."""
    frontera = uuid.uuid4().hex
    tipo = mimetypes.guess_type(ruta.name)[0] or "image/jpeg"
    partes = [f"--{frontera}\r\nContent-Disposition: form-data; name=\"tipo\"\r\n\r\nfoto\r\n".encode(),
              f"--{frontera}\r\nContent-Disposition: form-data; name=\"archivos\"; filename=\"{ruta.name}\"\r\n"
              f"Content-Type: {tipo}\r\n\r\n".encode() + ruta.read_bytes() + b"\r\n",
              f"--{frontera}--\r\n".encode()]
    estado, cuerpo = pedir("POST", "/documentos", b"".join(partes), f"multipart/form-data; boundary={frontera}")
    assert estado == 201, f"No se pudo cargar la foto de prueba ({estado}): {cuerpo}"
    return cuerpo["documentos"][0]


# ───────────────────────────── fixtures ─────────────────────────────
@pytest.fixture(scope="session")
def sistema_listo() -> dict:
    """Espera a que la web responda y la API no reporte fallas (modelos descargados y cargados en memoria)."""
    limite, ultimo = time.monotonic() + ESPERA_SALUD_S, None
    while time.monotonic() < limite:
        try:
            estado, salud = pedir("GET", "/health")
            ultimo = salud.get("estado", estado)
            precalentando = (salud.get("precalentamiento") or {}).get("estado") == "en_curso"
            if estado == 200 and ultimo in ("ok", "degradado") and not precalentando:
                return salud
        except (urllib.error.URLError, OSError, ValueError) as e:
            ultimo = repr(e)
        time.sleep(5)
    pytest.fail(f"El sistema no estuvo listo en {ESPERA_SALUD_S:.0f} s (último estado: {ultimo}).")


@pytest.fixture(scope="session")
def navegador():
    with sync_playwright() as p:
        # /dev/shm de Docker es pequeño: Chromium usa /tmp en su lugar
        b = p.chromium.launch(args=["--disable-dev-shm-usage"])
        yield b
        b.close()


@dataclass
class Sesion:
    pagina: Page
    peticiones: list[str] = field(default_factory=list)
    errores_js: list[str] = field(default_factory=list)

    def verificar_r8(self) -> None:
        """R8: el navegador solo habló con la web (mismo origen) y, para datos, solo con /api/*."""
        origen = urlsplit(URL_WEB).netloc
        ajenas = [u for u in self.peticiones if urlsplit(u).scheme in ("http", "https") and urlsplit(u).netloc != origen]
        assert not ajenas, f"Peticiones fuera de la web: {ajenas[:5]}"
        prohibidas = [u for u in self.peticiones if any(x in u.lower() for x in ("11434", "6333", "ollama", "qdrant"))]
        assert not prohibidas, f"La web habló con los modelos o la base vectorial: {prohibidas[:5]}"
        assert not self.errores_js, f"Errores de JavaScript en la página: {self.errores_js[:5]}"


@pytest.fixture
def sesion(navegador, sistema_listo):
    contexto = navegador.new_context(base_url=URL_WEB, locale="es-MX", viewport={"width": 1280, "height": 900})
    contexto.set_default_timeout(60_000)
    pagina = contexto.new_page()
    s = Sesion(pagina)
    pagina.on("request", lambda r: s.peticiones.append(r.url))
    pagina.on("pageerror", lambda e: s.errores_js.append(str(e)))
    yield s
    contexto.close()


@pytest.fixture(scope="session")
def foto_de_prueba() -> Path:
    """Una foto que NO esté en el archivo de referencia: catalogarla nunca debe tocar las fichas de referencia."""
    explicita = os.environ.get("FOTOTECA_E2E_FOTO")
    if explicita:
        ruta = Path(explicita)
        assert ruta.is_file(), f"FOTOTECA_E2E_FOTO no existe dentro del contenedor: {ruta}"
        return ruta
    demo = sorted(p for p in (DATOS / "demo").glob("*") if p.suffix.lower() in EXTENSIONES)
    if demo:
        return demo[0]
    particiones = EVALUACION / "conjuntos" / "particiones.json"
    if particiones.is_file():
        for documento in json.loads(particiones.read_text(encoding="utf-8"))["particiones"].get("nuevas", []):
            ruta = DATOS / "crudos" / "xm3600" / "imagenes" / f"{documento.removeprefix('xm-')}.jpg"
            if ruta.is_file():
                return ruta
    pytest.skip("No hay foto de prueba: define FOTOTECA_E2E_FOTO o prepara data/demo/ o la partición `nuevas`.")
