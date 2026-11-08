"""Ajustes documentados de h0.json entre corridas de H0 (se ejecuta dentro del contenedor).

1. Conserva el resultado de la 1ª corrida de 0.2 (presence_penalty 0) como `0.2_corrida1`, porque la corrida 3
   repite 0.2 con presence_penalty 1.5 y lo sobrescribiría. Es la evidencia del diagnóstico (docs/BLOQUEOS.md).
2. Recalcula la elección de lado de 0.3b con la regla corregida antes de usarla («el de menor tiempo entre los de
   calidad equivalente»; la regla original elegía el más pequeño aunque no fuera más rápido).
3. Con `--conservar-corrida4 <log>`: conserva 0.5 y 0.6 de la corrida 4 (sin límite a la caché de prompts de
   llama-server) como `0.5_sin_limite_cache` y `0.6_corrida4`, antes de que la corrida 5 los sobrescriba. Es la
   evidencia de ADR-12 (proceso del modelo terminado por memoria). Las latencias de P1 que alcanzó a medir la
   corrida 4 solo quedaron en su log; se transcriben aquí tal cual para que las cifras citadas salgan de
   `evaluacion/resultados/`.

    python -m scripts._h0_ajustes [--conservar-corrida3] [--conservar-corrida4 /app/evaluacion_datos/logs/…log]
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from scripts._descargas import json_guardar
from scripts.verificar_h0 import H0_JSON, RESULTADOS, decisiones, incorporar_memoria


def _p1_del_log(ruta: Path) -> dict:
    """Líneas «0.6: P1 a 512px → {...}» del log de la corrida."""
    salida = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        m = re.search(r"0\.6: P1 a (\d+)px → (\{.*\})", linea)
        if m:
            salida[m.group(1)] = ast.literal_eval(m.group(2))
    return salida


def conservar_corrida4(datos: dict, ruta_log: Path) -> None:
    v = datos["verificaciones"]
    if "0.5" in v and "0.5_sin_limite_cache" not in v:
        v["0.5_sin_limite_cache"] = {
            **{k: x for k, x in v["0.5"].items() if k != "docker_stats"},
            "nota": "Corrida 4, con la caché de prompts de llama-server en su valor por defecto (8192 MiB por modelo). "
                    "El contenedor ollama llegó a su límite de 5g y el kernel mató un proceso del modelo durante 0.6 "
                    "(memory.events: oom_kill). Las latencias de estos ciclos se tomaron con el contenedor en su "
                    "límite de memoria. ADR-12.",
        }
        print("0.5 → 0.5_sin_limite_cache")
    if "0.5_sin_limite_cache" in v:  # se recalcula siempre desde los archivos «_antes» (no cambian)
        consigo = {"verificaciones": {"0.5": v["0.5_sin_limite_cache"]}}
        v["0.5_sin_limite_cache"]["docker_stats"] = incorporar_memoria(
            consigo, RESULTADOS / "h0_docker_stats_antes.jsonl", RESULTADOS / "h0_cgroup_ollama_antes.txt", clave="0.5")
    if "0.6" in v and "0.6_corrida4" not in v:
        v["0.6_corrida4"] = {
            **v["0.6"],
            "p1_por_lado_segun_log": _p1_del_log(ruta_log),
            "log": ruta_log.name,
            "nota": "La corrida 4 terminó en error cuando el kernel mató el proceso de Qwen por memoria (P3 de Qwen "
                    "solo texto). Las latencias de P1 a 1024 px NO son válidas: muchas fotos de XM3600 miden menos de "
                    "1024 px, la petición resultaba idéntica a la de 768 px y la caché de prompts la respondió sin "
                    "recalcular la imagen. 0.6 se repite completa en la corrida 5 con la caché desactivada.",
        }
        print("0.6 → 0.6_corrida4")


def main() -> None:
    import sys
    datos = json.loads(H0_JSON.read_text(encoding="utf-8"))
    v = datos["verificaciones"]
    if "--conservar-corrida4" in sys.argv:
        conservar_corrida4(datos, Path(sys.argv[sys.argv.index("--conservar-corrida4") + 1]))
    if "--conservar-corrida3" in sys.argv and "0.2" in v and "0.2_corrida3" not in v:
        v["0.2_corrida3"] = {**v["0.2"], "nota": "3ª corrida: presence_penalty 1.5, draft activo y P1 v1 (spec 07). "
                                                  "4/5 válidos: una foto rebasó num_predict. Motivó P1 v2 (más breve)."}
        print("0.2 → 0.2_corrida3")
    if "0.2_corrida1" not in v and "0.2" in v:
        v["0.2_corrida1"] = {**v["0.2"], "nota": "1ª corrida con presence_penalty 0 (sobrescrito por nosotros); "
                                                  "se conserva como evidencia. La corrida 3 repite 0.2 con 1.5."}
        print("0.2 → 0.2_corrida1")
    q = v.get("0.6b", {}).get("qwen_p1", {})
    if q:
        v["0.6b"]["analisis"] = {
            "cache_de_prompt": {k: x["prompt_eval"].get("p50_s") for k, x in q.items()},
            "tokens_por_s_generacion": {k: x["tokens_por_s_medio"] for k, x in q.items()},
            "conclusion": "La latencia total de las configuraciones que repitieron exactamente el prompt anterior con la "
                          "misma imagen está sesgada: Ollama reutilizó la caché de prompt (prefill de ~0.25 s en lugar de "
                          "~23 s). Por eso el efecto del draft se decide con la velocidad de generación: sin draft Qwen "
                          "genera más tokens por segundo. Decisión: draft_num_predict 0 para Qwen. presence_penalty 1.5 "
                          "elimina la repetición; sin `format` no hay JSON válido; num_predict 500 alarga la salida.",
        }
    por_lado = v.get("0.3b", {}).get("por_lado", {})
    if por_lado:  # determinista a partir de los datos: se puede repetir sin cambiar el resultado
        mejor = max(x["r5_texto_a_imagen"] for x in por_lado.values())
        candidatos = [k for k, x in por_lado.items()
                      if x["r5_texto_a_imagen"] >= mejor - 0.04 and x["tasa_par_correcto_gana"] >= 0.80]
        elegido = min(candidatos, key=lambda k: por_lado[k]["segundos_por_imagen"])
        original = min(candidatos, key=int)
        v["0.3b"]["lado_elegido"] = {
            "px": int(elegido),
            "regla": "entre los lados con calidad equivalente (R@5 a ≤0.04 del mejor y tasa de acierto ≥0.80), el de "
                     "menor tiempo por imagen",
            "nota": f"recalculado con la regla corregida; la regla original («el lado más pequeño de calidad "
                    f"equivalente») daba {original} px"}
        print(f"0.3b lado: regla original {original} → regla corregida {elegido}")
    datos["decisiones"] = decisiones(v)
    json_guardar(H0_JSON, datos)


if __name__ == "__main__":
    main()
