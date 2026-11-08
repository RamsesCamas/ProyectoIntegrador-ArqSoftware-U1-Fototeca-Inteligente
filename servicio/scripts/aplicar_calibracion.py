"""Aplica los umbrales calibrados: escribe `config/calibracion.yaml`, que el servicio mezcla sobre `parametros.yaml`.

    python -m scripts.aplicar_calibracion            # todo lo que ya esté calibrado
    python -m scripts.aplicar_calibracion --mostrar  # solo muestra lo que aplicaría

Lee los resultados de calibración que existan en `evaluacion/resultados/` y toma de cada uno el valor elegido con su
regla documentada:
- `calibracion_tesauro.json` (indexar_archivo): τ_tesauro con el proxy léxico.
- `calibracion_h4.json` (calibrar h4): τ_ret, τ_consenso inicial, τ_busqueda, τ_apego_visual y τ_consistencia.
- `calibracion_h5.json` (calibrar h5): τ_fuera_dominio, τ_texto_visible y τ_inyeccion.
- `cache.json` (evaluación): τ_dup = máximo recall con FPR ≤ 2 % (ADR-04).
- `enrutador.json` (evaluación): τ_consenso y τ_acuerdo con la restricción de latencia (ADR-03); sustituyen a los de H4.
Cada valor queda con su archivo de origen en `_origen`. Cambiar la calibración cambia la versión de configuración y,
con ella, invalida la caché de fichas. Si un archivo no existe, sus umbrales se quedan como estén.
"""
from __future__ import annotations

import argparse
import json

import yaml

from scripts._descargas import EVAL, ahora_iso, registro

RESULTADOS = EVAL / "resultados"


def _leer(nombre: str) -> dict | None:
    ruta = RESULTADOS / nombre
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None


def umbrales_disponibles() -> dict[str, tuple[float, str]]:
    """{"seccion.clave": (valor, origen)} en el orden en que se aplican (los posteriores ganan)."""
    salida: dict[str, tuple[float, str]] = {}
    t = _leer("calibracion_tesauro.json")
    if t and t.get("tau_elegido") is not None:
        salida["guardrails.tau_tesauro"] = (float(t["tau_elegido"]), "calibracion_tesauro.json → tau_elegido")
    for fase in ("h4", "h5"):
        d = _leer(f"calibracion_{fase}.json")
        for clave, valor in ((d or {}).get("umbrales") or {}).items():
            if valor is not None:
                salida[clave] = (float(valor), f"calibracion_{fase}.json → umbrales.{clave}")
    cache = _leer("cache.json")
    tau_dup = (((cache or {}).get("metricas") or {}).get("fichas_semantica_tau_dup") or {}).get("tau_elegido")
    if tau_dup is not None:
        salida["cache.fichas.tau_dup"] = (float(tau_dup), "cache.json → metricas.fichas_semantica_tau_dup.tau_elegido")
    enr = _leer("enrutador.json")
    elegidos = ((((enr or {}).get("metricas") or {}).get("fichas") or {}).get("umbrales_elegidos") or {})
    for clave in ("enrutador_fichas.tau_consenso", "enrutador_fichas.tau_acuerdo"):
        if elegidos.get(clave) is not None:
            salida[clave] = (float(elegidos[clave]), f"enrutador.json → metricas.fichas.umbrales_elegidos.{clave}")
    return salida


def como_arbol(umbrales: dict[str, tuple[float, str]]) -> dict:
    arbol: dict = {"_generado": ahora_iso(), "_origen": {}}
    for clave, (valor, origen) in umbrales.items():
        nodo = arbol
        *ruta, hoja = clave.split(".")
        for parte in ruta:
            nodo = nodo.setdefault(parte, {})
        nodo[hoja] = round(valor, 4)
        arbol["_origen"][clave] = origen
    return arbol


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mostrar", action="store_true", help="no escribe; solo muestra los umbrales")
    args = ap.parse_args()
    from fototeca.api.arranque import DIR_SERVICIO
    umbrales = umbrales_disponibles()
    if not umbrales:
        registro("no hay resultados de calibración todavía; no se escribe nada")
        return
    for clave, (valor, origen) in umbrales.items():
        registro(f"   {clave} = {round(valor, 4)}  ({origen})")
    if args.mostrar:
        return
    ruta = DIR_SERVICIO / "config" / "calibracion.yaml"
    encabezado = ("# Umbrales calibrados con datos. Lo genera `python -m scripts.aplicar_calibracion`; no se edita a mano.\n"
                  "# El servicio lo mezcla sobre parametros.yaml (fototeca/api/arranque.py → fusionar_calibracion).\n")
    ruta.write_text(encabezado + yaml.safe_dump(como_arbol(umbrales), allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    registro(f"escrito {ruta.relative_to(DIR_SERVICIO)} con {len(umbrales)} umbrales")


if __name__ == "__main__":
    main()
