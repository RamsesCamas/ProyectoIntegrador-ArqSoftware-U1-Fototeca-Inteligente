"""Calibra los tiempos límite de las llamadas a los modelos con lo que registró la bitácora del servicio.

    docker compose run --rm servicio python -m scripts.calibrar_tiempos_limite

Antes: 1.5 × el p95 de H0 (P1 sobre 5 fotos), 58 s para Qwen con imagen. Una foto con mucho texto (la página de un
libro) hizo que P1 tardara 61.1 s sin competencia (310 tokens de salida de 350 posibles): agotó el límite, el
reintento idéntico lo volvió a agotar, P2 también, y la ficha salió degradada tras 4 minutos.

Regla, fijada antes de calcular: límite = 1.5 × el MÁXIMO observado en las llamadas exitosas de la bitácora (eventos
C6 `llamada_modelo` con resultado ok), por tipo de llamada, redondeado hacia arriba al segundo y nunca por debajo del
límite vigente en `parametros.yaml`. Tipos: Qwen con imagen (P1 y P2) → `qwen_imagen`; Qwen solo texto (P3 y P6) →
`qwen_texto`; LFM3 (P3, P4, P5 y P7) → `lfm3`. El máximo (no el p95) cubre las fotos pesadas que el p95 deja fuera;
como el cliente ya espera el turno del modelo antes de contar el tiempo y el gateway no repite una llamada que agotó
su tiempo, un límite holgado solo pesa en los casos raros.

Solo lee la bitácora. Escribe `evaluacion/resultados/calibracion_tiempos_limite.json`; lo aplica
`scripts.aplicar_calibracion` a `config/calibracion.yaml`.
"""
from __future__ import annotations

import json
import math
import sqlite3
import statistics

from fototeca.api.arranque import cargar_configuracion
from scripts._descargas import EVAL, ahora_iso, json_guardar, registro

SALIDA = EVAL / "resultados" / "calibracion_tiempos_limite.json"
FACTOR = 1.5


def tipo_de_llamada(modelo: str, tarea: str | None, modelos: dict) -> str | None:
    if modelo == modelos["vision"]:
        return "qwen_imagen" if tarea in ("P1", "P2") else "qwen_texto"
    if modelo == modelos["composicion"]:
        return "lfm3"
    return None


def main() -> None:
    config = cargar_configuracion(con_calibracion=False)
    vigentes = config.parametro("tiempos_limite_s", {}) or {}
    duraciones: dict[str, list[float]] = {}
    agotados: dict[str, int] = {}
    tareas: dict[str, set] = {}
    con = sqlite3.connect(f"file:{config.rutas['sqlite']}?mode=ro", uri=True)
    for modelo, duracion_ms, resultado, detalle in con.execute(
            "SELECT modelo, duracion_ms, resultado, detalle FROM eventos WHERE evento = 'llamada_modelo'"):
        tarea = json.loads(detalle or "{}").get("tarea")
        tipo = tipo_de_llamada(modelo, tarea, config.modelos)
        if tipo is None:
            continue
        tareas.setdefault(tipo, set()).add(tarea)
        if resultado == "ok" and duracion_ms:
            duraciones.setdefault(tipo, []).append(duracion_ms / 1000)
        elif resultado == "tiempo_agotado":
            agotados[tipo] = agotados.get(tipo, 0) + 1
    por_llamada, limites = {}, {}
    for tipo, valores in sorted(duraciones.items()):
        valores.sort()
        p95 = valores[min(len(valores) - 1, round(0.95 * (len(valores) - 1)))]
        anterior = float(vigentes.get(tipo, 0))
        limite = max(anterior, math.ceil(FACTOR * valores[-1]))
        limites[tipo] = limite
        por_llamada[tipo] = {
            "tareas": sorted(t for t in tareas.get(tipo, set()) if t), "n_exitosas": len(valores),
            "tiempo_agotado": agotados.get(tipo, 0), "p50_s": round(statistics.median(valores), 1),
            "p95_s": round(p95, 1), "max_s": round(valores[-1], 1), "limite_anterior_s": anterior, "limite_s": limite,
        }
        registro(f"{tipo}: n={len(valores)} p95={p95:.1f}s máx={valores[-1]:.1f}s → {anterior:.0f} s ⇒ {limite} s")
    json_guardar(SALIDA, {
        "modulo": "calibracion_tiempos_limite",
        "fecha": ahora_iso(),
        "descripcion": __doc__.strip().splitlines()[0],
        "regla": f"límite = {FACTOR} × máximo observado en llamadas exitosas, hacia arriba al segundo, "
                 "nunca por debajo del vigente en parametros.yaml",
        "fuente": "eventos C6 llamada_modelo de la bitácora del servicio (SQLite)",
        "por_llamada": por_llamada,
        "tiempos_limite_s": limites,
    })
    registro(f"→ {SALIDA}")


if __name__ == "__main__":
    main()
