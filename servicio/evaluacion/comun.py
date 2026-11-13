"""Utilidades compartidas por los módulos de evaluación."""
from __future__ import annotations

import csv
import json
import os
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

EVAL = Path(os.environ.get("FOTOTECA_EVAL", "/app/evaluacion_datos"))
DATA = Path(os.environ.get("FOTOTECA_DATA", "/app/data"))
CONJUNTOS, RESULTADOS, GRAFICAS, REVISION = EVAL / "conjuntos", EVAL / "resultados", EVAL / "graficas", EVAL / "revision_manual"
SEMILLA = 2026


def rapido() -> bool:
    return os.environ.get("FOTOTECA_EVAL_RAPIDO", "0") == "1"


def fraccion() -> float:
    """Fracción de cada conjunto que se evalúa: 1 (completa), 0.25 con --rapido, o la de --fraccion. Los módulos toman
    el INICIO de la misma muestra con semilla fija, así que una corrida mayor reutiliza los casos ya calculados."""
    if rapido():
        return 0.25
    try:
        f = float(os.environ.get("FOTOTECA_EVAL_FRACCION", "1"))
    except ValueError:
        f = 1.0
    return min(1.0, max(0.05, f))


def tamano(n: int) -> int:
    """Con --rapido, la cuarta parte (pruebas de humo); con --fraccion f, round(n·f) (mínimo 2)."""
    if rapido():
        return max(2, n // 4)
    f = fraccion()
    return n if f >= 1.0 else min(n, max(2, int(round(n * f))))


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def registro(mensaje: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {mensaje}", flush=True)


def leer_conjunto(nombre: str) -> dict:
    return json.loads((CONJUNTOS / f"{nombre}.json").read_text(encoding="utf-8"))


def particiones() -> dict:
    return leer_conjunto("particiones")["particiones"]


def hardware() -> dict:
    info = {"maquina": platform.machine(), "nproc": os.cpu_count(), "python": platform.python_version()}
    try:
        salida = subprocess.run(["lscpu"], capture_output=True, text=True, timeout=10).stdout
        for linea in salida.splitlines():
            k, _, v = linea.partition(":")
            if k.strip() in ("Architecture", "Model name", "Vendor ID", "CPU(s)"):
                info[f"lscpu_{k.strip()}"] = v.strip()
    except Exception:  # noqa: BLE001
        pass
    try:
        v = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        info["limite_memoria_contenedor_bytes"] = None if v == "max" else int(v)
    except Exception:  # noqa: BLE001
        pass
    return info


def percentiles(valores: list[float], unidad: str = "s") -> dict:
    if not valores:
        return {"n": 0}
    a = np.asarray(valores, dtype=float)
    return {"n": int(a.size), f"media_{unidad}": round(float(a.mean()), 3), f"p50_{unidad}": round(float(np.percentile(a, 50)), 3),
            f"p95_{unidad}": round(float(np.percentile(a, 95)), 3), f"max_{unidad}": round(float(a.max()), 3)}


class ClienteEval:
    """La API real, en el mismo proceso (pasa por todas las capas y deja trazas en la misma SQLite)."""

    def __init__(self):
        os.environ["MODO_EVALUACION"] = "1"
        from fastapi.testclient import TestClient

        from fototeca.api.arranque import cargar_configuracion, construir_contenedor, crear_app
        self.contenedor = construir_contenedor(cargar_configuracion(modo_evaluacion=True))
        self.http = TestClient(crear_app(self.contenedor, precalentar=False), raise_server_exceptions=False)
        self.config = self.contenedor.config

    def version_configuracion(self) -> str:
        return self.config.version_configuracion(self.contenedor.almacen_documentos.leer_estado("version_corpus", "sin_corpus"))

    def subir_foto(self, ruta: Path, nombre: str | None = None) -> dict:
        with open(ruta, "rb") as f:
            r = self.http.post("/documentos", data={"tipo": "foto"}, files=[("archivos", (nombre or ruta.name, f, "image/jpeg"))])
        return {"estado_http": r.status_code, **r.json()}

    def ficha(self, documento_id: str, **opciones) -> tuple[int, dict, float]:
        t0 = time.perf_counter()
        r = self.http.post("/fichas", json={"documento_id": documento_id, **opciones})
        return r.status_code, r.json(), time.perf_counter() - t0

    def buscar(self, texto: str, **opciones) -> tuple[int, dict, float]:
        t0 = time.perf_counter()
        r = self.http.post("/busquedas", json={"texto": texto, **opciones})
        return r.status_code, r.json(), time.perf_counter() - t0

    def buscar_imagen(self, ruta: Path, k: int = 12) -> tuple[int, dict, float]:
        t0 = time.perf_counter()
        with open(ruta, "rb") as f:
            r = self.http.post("/busquedas", data={"k": str(k)}, files=[("imagen", (ruta.name, f, "image/jpeg"))])
        return r.status_code, r.json(), time.perf_counter() - t0

    def retroalimentacion(self, traza_id: str, **campos) -> tuple[int, dict]:
        r = self.http.post("/retroalimentacion", json={"traza_id": traza_id, **campos})
        return r.status_code, r.json()

    def eliminar(self, documento_id: str) -> int:
        return self.http.delete(f"/documentos/{documento_id}").status_code


class Incremental:
    """Resultados caso por caso en JSONL: si el proceso se interrumpe, se reanuda donde se quedó."""

    def __init__(self, nombre: str):
        self.ruta = RESULTADOS / "casos" / f"{nombre}.jsonl"
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.casos: dict[str, dict] = {}
        if self.ruta.exists():
            for linea in self.ruta.read_text(encoding="utf-8").splitlines():
                if linea.strip():
                    c = json.loads(linea)
                    self.casos[c["clave"]] = c

    def obtener(self, clave: str) -> dict | None:
        return self.casos.get(clave)

    def guardar(self, clave: str, registro: dict) -> dict:
        registro = {"clave": clave, **registro}
        self.casos[clave] = registro
        with open(self.ruta, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False, default=str) + "\n")
        return registro


def guardar_resultado(modulo: str, metricas: dict, detalle: list[dict] | None = None, configuracion: dict | None = None,
                      cliente: ClienteEval | None = None) -> Path:
    RESULTADOS.mkdir(parents=True, exist_ok=True)
    cuerpo = {"modulo": modulo, "fecha": ahora(), "rapido": rapido(), "fraccion": fraccion(), "hardware": hardware(),
              "version_configuracion": cliente.version_configuracion() if cliente else None,
              "configuracion": configuracion or {}, "metricas": metricas}
    ruta = RESULTADOS / f"{modulo}.json"
    ruta.write_text(json.dumps(cuerpo, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if detalle:
        columnas = sorted({k for fila in detalle for k in fila})
        with open(RESULTADOS / f"{modulo}_detalle.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=columnas)
            w.writeheader()
            for fila in detalle:
                w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in fila.items()})
    registro(f"resultado → {ruta.name}")
    return ruta


def guardar_grafica(nombre: str, figura) -> Path:
    GRAFICAS.mkdir(parents=True, exist_ok=True)
    ruta = GRAFICAS / f"{nombre}.png"
    figura.savefig(ruta, dpi=150, bbox_inches="tight")
    import matplotlib.pyplot as plt
    plt.close(figura)
    return ruta


def plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as pyplot
    pyplot.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    return pyplot
