"""Antes y después de P2/P3 v4 en las mismas fotos de evaluación (sin llamar a modelos).

    python -m evaluacion.antes_despues_prompts

Lee los casos guardados de cada configuración de ficha (con el modelo que compuso cada una: desde R3, P3 lo compone Qwen,
así que en `con_rag` y `sin_rag` el «después» cambia de prompt y de modelo): el «antes» (`casos/fichas_<config>_p2p3_v2.jsonl`, generado con
P2/P3 v2) y el «después» (`casos/fichas_<config>.jsonl`, con la versión vigente). Compara solo las fotos que están en
los dos. Por configuración reporta las fichas con `requiere_revision`, sus motivos, los titulares vacíos y la
verificación `copia_contexto`: la que registró el flujo o, en los casos v2 (anteriores a ella), la misma función
aplicada a la ficha guardada (`calidad.copia_contexto_caso`). Escribe
`evaluacion/resultados/antes_despues_prompts.json`.
"""
from __future__ import annotations

import json
from collections import Counter

from evaluacion.calidad import copia_contexto_caso, resumen_copia_contexto
from evaluacion.comun import RESULTADOS, ahora, registro

CONFIGS = ("qwen_rapida", "qwen_composicion", "lfm3_composicion", "con_rag", "sin_rag")
SUFIJO_ANTES = "_p2p3_v2"


def _leer(nombre: str) -> dict[str, dict]:
    ruta = RESULTADOS / "casos" / f"{nombre}.jsonl"
    casos: dict[str, dict] = {}
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                c = json.loads(linea)
                casos[c["clave"]] = c
    return casos


def _resumen(casos: list[dict]) -> dict:
    respuestas = [c.get("respuesta") or {} for c in casos]
    fichas = [r.get("ficha") or {} for r in respuestas]
    motivos = Counter(m for r in respuestas for m in ((r.get("meta") or {}).get("revision") or []))
    return {
        "n": len(casos),
        "estado_http_200": sum(1 for c in casos if c.get("estado_http") == 200),
        "requiere_revision": sum(1 for f in fichas if f.get("estado") == "requiere_revision"),
        "titulares_vacios": sum(1 for f in fichas if not f.get("titular")),
        "motivos_revision": dict(motivos.most_common()),
        "copia_contexto": resumen_copia_contexto([copia_contexto_caso(r) for r in respuestas]),
        "modelo_que_compuso": dict(Counter(((r.get("meta") or {}).get("modelos") or {}).get("composicion")
                                           or ((r.get("meta") or {}).get("modelos") or {}).get("vision") or "sin dato"
                                           for r in respuestas)),
        "versiones_configuracion": sorted({str((r.get("meta") or {}).get("version_configuracion"))
                                          for r in respuestas} - {"None"}),
    }


def main() -> None:
    salida = {}
    for config in CONFIGS:
        antes, despues = _leer(f"fichas_{config}{SUFIJO_ANTES}"), _leer(f"fichas_{config}")
        comunes = sorted(set(antes) & set(despues))
        if not comunes:
            registro(f"{config}: sin fotos en común (antes {len(antes)}, después {len(despues)})")
            continue
        salida[config] = {"fotos_en_comun": len(comunes),
                          "antes_p2p3_v2": _resumen([antes[k] for k in comunes]),
                          "despues": _resumen([despues[k] for k in comunes])}
        a, d = salida[config]["antes_p2p3_v2"], salida[config]["despues"]
        registro(f"{config}: requiere_revision {a['requiere_revision']} → {d['requiere_revision']} de {len(comunes)} · "
                 f"fichas con copia {a['copia_contexto'].get('fichas_con_copia')} → "
                 f"{d['copia_contexto'].get('fichas_con_copia')}")
    ruta = RESULTADOS / "antes_despues_prompts.json"
    ruta.write_text(json.dumps({"fecha": ahora(), "antes": "P2/P3 v2 (casos con sufijo _p2p3_v2)",
                                "despues": "versión vigente de los prompts (casos sin sufijo)",
                                "configuraciones": salida}, ensure_ascii=False, indent=2), encoding="utf-8")
    registro(f"resultado → {ruta.name}")


if __name__ == "__main__":
    main()
