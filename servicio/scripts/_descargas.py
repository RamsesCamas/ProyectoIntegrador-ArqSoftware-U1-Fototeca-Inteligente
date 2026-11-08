"""Descargas idempotentes con SHA-256 y manifiestos de las fuentes de `config/fuentes.yaml`.

- Si un archivo ya existe y su SHA-256 coincide con el registrado, no se vuelve a descargar.
- Cada descarga queda en `data/manifiesto_<nombre>.json` con URL, fecha, tamaño y SHA-256.
- `filtrar_csv_remoto` lee un CSV remoto en streaming y guarda solo las filas que interesan: el original
  no se escribe en disco, pero se registran su tamaño y su SHA-256 (calculado al vuelo).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import httpx
import yaml

DATA = Path(os.environ.get("FOTOTECA_DATA", "/app/data"))
EVAL = Path(os.environ.get("FOTOTECA_EVAL", "/app/evaluacion_datos"))
CONFIG = Path(os.environ.get("FOTOTECA_CONFIG", Path(__file__).resolve().parent.parent / "config"))
AGENTE = "FototecaViva/0.1 (proyecto academico MCIT UPChiapas; preparacion de datos)"


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def registro(mensaje: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {mensaje}", flush=True)


def cargar_fuentes() -> dict:
    return yaml.safe_load((CONFIG / "fuentes.yaml").read_text(encoding="utf-8"))


def sha256_archivo(ruta: Path, bloque: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for b in iter(lambda: f.read(bloque), b""):
            h.update(b)
    return h.hexdigest()


class Manifiesto:
    """Manifiesto de archivos descargados o derivados (`data/manifiesto_<nombre>.json`)."""

    def __init__(self, nombre: str):
        self.ruta = DATA / f"manifiesto_{nombre}.json"
        self.entradas: dict[str, dict] = {}
        if self.ruta.exists():
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
            self.entradas = {e["archivo"]: e for e in datos.get("archivos", [])}

    def obtener(self, archivo: str) -> dict | None:
        return self.entradas.get(archivo)

    def registrar(self, entrada: dict) -> dict:
        self.entradas[entrada["archivo"]] = entrada
        self.guardar()
        return entrada

    def guardar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        cuerpo = {
            "actualizado": ahora_iso(),
            "archivos": sorted(self.entradas.values(), key=lambda e: e["archivo"]),
        }
        tmp = self.ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(cuerpo, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.ruta)


def _cliente_http() -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(60.0, read=300.0),
        headers={"User-Agent": AGENTE},
    )


def descargar(
    url: str,
    destino_rel: str,
    manifiesto: Manifiesto,
    sha256_esperado: str | None = None,
    reintentos: int = 3,
) -> dict:
    """Descarga `url` a `data/<destino_rel>` salvo que ya exista con el SHA-256 correcto."""
    destino = DATA / destino_rel
    previo = manifiesto.obtener(destino_rel)
    if destino.exists():
        esperado = sha256_esperado or (previo or {}).get("sha256")
        actual = sha256_archivo(destino)
        if esperado is None or actual == esperado:
            if previo is None:
                previo = manifiesto.registrar({
                    "archivo": destino_rel, "url": url, "fecha": ahora_iso(),
                    "tamano_bytes": destino.stat().st_size, "sha256": actual,
                    "nota": "ya existía; se registró sin volver a descargar",
                })
            registro(f"ya existe y su SHA-256 coincide: {destino_rel}")
            return previo
        registro(f"SHA-256 distinto ({actual[:12]}… ≠ {esperado[:12]}…): se vuelve a descargar {destino_rel}")

    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + ".parcial")
    for intento in range(1, reintentos + 1):
        try:
            registro(f"descargando {url}")
            h, n, t0 = hashlib.sha256(), 0, time.perf_counter()
            with _cliente_http() as cliente, cliente.stream("GET", url) as r:
                r.raise_for_status()
                with open(parcial, "wb") as f:
                    for bloque in r.iter_bytes(1 << 20):
                        f.write(bloque)
                        h.update(bloque)
                        n += len(bloque)
            digest = h.hexdigest()
            if sha256_esperado and digest != sha256_esperado:
                raise ValueError(f"SHA-256 no coincide: {digest} ≠ {sha256_esperado}")
            parcial.replace(destino)
            registro(f"  {n / 1e6:.1f} MB en {time.perf_counter() - t0:.0f} s")
            return manifiesto.registrar({
                "archivo": destino_rel, "url": url, "fecha": ahora_iso(),
                "tamano_bytes": n, "sha256": digest,
            })
        except Exception as e:  # noqa: BLE001 — se reintenta cualquier fallo de red o de E/S
            registro(f"  intento {intento}/{reintentos} falló: {e}")
            if intento == reintentos:
                raise
            time.sleep(5 * intento)
    raise RuntimeError("inalcanzable")


def filtrar_csv_remoto(
    urls: Iterable[str],
    destino_rel: str,
    columna: str,
    valores: set[str],
    manifiesto: Manifiesto,
    reintentos: int = 3,
    progreso: Callable[[str], None] = registro,
) -> dict:
    """Lee CSVs remotos en streaming y guarda en un solo CSV las filas cuya `columna` está en `valores`.

    Agrega la columna `origen` con el nombre del archivo remoto. Idempotente: si el destino existe y su
    SHA-256 coincide con el del manifiesto, no se vuelve a leer nada.
    """
    urls = list(urls)
    destino = DATA / destino_rel
    previo = manifiesto.obtener(destino_rel)
    if destino.exists() and previo and sha256_archivo(destino) == previo["sha256"]:
        registro(f"ya existe y su SHA-256 coincide: {destino_rel}")
        return previo

    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + ".parcial")
    origenes = []
    with open(parcial, "w", newline="", encoding="utf-8") as fout:
        escritor = None
        for url in urls:
            nombre = url.rsplit("/", 1)[-1]
            for intento in range(1, reintentos + 1):
                try:
                    progreso(f"leyendo en streaming {nombre}")
                    h, n_bytes, n_filas, n_guardadas, t0 = hashlib.sha256(), 0, 0, 0, time.perf_counter()
                    filas_url: list[list[str]] = []
                    encabezado: list[str] | None = None
                    resto = b""
                    with _cliente_http() as cliente, cliente.stream("GET", url) as r:
                        r.raise_for_status()
                        for bloque in r.iter_bytes(1 << 20):
                            h.update(bloque)
                            n_bytes += len(bloque)
                            datos = resto + bloque
                            lineas = datos.split(b"\n")
                            resto = lineas.pop()
                            for linea in lineas:
                                texto = linea.decode("utf-8").rstrip("\r")
                                if not texto:
                                    continue
                                campos = next(csv.reader([texto]))
                                if encabezado is None:
                                    encabezado = campos
                                    idx = encabezado.index(columna)
                                    continue
                                n_filas += 1
                                if campos[idx] in valores:
                                    filas_url.append(campos)
                            if n_bytes % (200 << 20) < len(bloque):
                                progreso(f"  {nombre}: {n_bytes / 1e6:.0f} MB leídos, {len(filas_url)} filas útiles")
                        if resto.strip():
                            campos = next(csv.reader([resto.decode("utf-8").rstrip("\r")]))
                            n_filas += 1
                            if encabezado and campos[idx] in valores:
                                filas_url.append(campos)
                    if encabezado is None:
                        raise ValueError(f"{nombre}: CSV vacío")
                    if escritor is None:
                        escritor = csv.writer(fout)
                        escritor.writerow(encabezado + ["origen"])
                    for campos in filas_url:
                        escritor.writerow(campos + [nombre])
                    n_guardadas = len(filas_url)
                    origenes.append({
                        "url": url, "fecha": ahora_iso(), "tamano_bytes": n_bytes,
                        "sha256": h.hexdigest(), "filas": n_filas, "filas_guardadas": n_guardadas,
                        "segundos": round(time.perf_counter() - t0, 1),
                    })
                    progreso(f"  {nombre}: {n_bytes / 1e6:.0f} MB, {n_filas} filas, {n_guardadas} guardadas")
                    break
                except Exception as e:  # noqa: BLE001
                    progreso(f"  intento {intento}/{reintentos} con {nombre} falló: {e}")
                    if intento == reintentos:
                        raise
                    time.sleep(5 * intento)
    parcial.replace(destino)
    return manifiesto.registrar({
        "archivo": destino_rel, "fecha": ahora_iso(), "tamano_bytes": destino.stat().st_size,
        "sha256": sha256_archivo(destino), "derivado_de": origenes,
        "nota": f"filas con {columna} en un conjunto de {len(valores)} valores; originales no guardados",
    })


def leer_csv(ruta: Path) -> list[dict]:
    with open(ruta, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def json_guardar(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(ruta)


def texto_a_bytes_io(texto: str) -> io.BytesIO:
    return io.BytesIO(texto.encode("utf-8"))
