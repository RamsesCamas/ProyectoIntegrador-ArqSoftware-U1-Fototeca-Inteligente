"""La calibración se aplica sin editar parametros.yaml: config/calibracion.yaml se mezcla sobre los parámetros."""
from __future__ import annotations

import json
import shutil

import yaml

from fototeca.api.arranque import DIR_SERVICIO, cargar_configuracion, fusionar_calibracion


def test_fusion_respeta_lo_no_calibrado_e_ignora_metadatos():
    base = {"agente": {"max_iter": 2, "delta_margen": 0.02}, "cache": {"fichas": {"tau_dup": 0.97, "ttl_s": 10}}}
    mezcla = fusionar_calibracion(base, {"_origen": {"x": "y"}, "agente": {"tau_ret": 0.61},
                                         "cache": {"fichas": {"tau_dup": 0.95}}})
    assert mezcla["agente"] == {"max_iter": 2, "delta_margen": 0.02, "tau_ret": 0.61}
    assert mezcla["cache"]["fichas"] == {"tau_dup": 0.95, "ttl_s": 10} and "_origen" not in mezcla
    assert base["cache"]["fichas"]["tau_dup"] == 0.97                      # no muta el original


def test_cargar_configuracion_lee_calibracion_y_cambia_la_version(tmp_path, monkeypatch):
    shutil.copy(DIR_SERVICIO / "config" / "parametros.yaml", tmp_path / "parametros.yaml")
    monkeypatch.setenv("FOTOTECA_CONFIG", str(tmp_path))
    sin = cargar_configuracion()
    (tmp_path / "calibracion.yaml").write_text(yaml.safe_dump({"agente": {"tau_ret": 0.61}}), encoding="utf-8")
    con = cargar_configuracion()
    assert con.parametro("agente.tau_ret") == 0.61 and sin.parametro("agente.tau_ret") is None
    assert con.version_configuracion("c") != sin.version_configuracion("c")   # invalida la caché


def test_aplicar_calibracion_toma_los_valores_elegidos(tmp_path, monkeypatch):
    import scripts.aplicar_calibracion as ap
    (tmp_path / "calibracion_h4.json").write_text(json.dumps({"umbrales": {"agente.tau_ret": 0.6, "guardrails.tau_apego_visual": 0.2}}))
    (tmp_path / "enrutador.json").write_text(json.dumps({"metricas": {"fichas": {"umbrales_elegidos": {
        "enrutador_fichas.tau_consenso": 0.7, "enrutador_fichas.tau_acuerdo": 0.3, "nota": "x"}}}}))
    (tmp_path / "cache.json").write_text(json.dumps({"metricas": {"fichas_semantica_tau_dup": {"tau_elegido": 0.95}}}))
    (tmp_path / "calibracion_tau_excluir.json").write_text(json.dumps({"tau_excluir": 0.73, "tau_anterior": 0.6}))
    monkeypatch.setattr(ap, "RESULTADOS", tmp_path)
    arbol = ap.como_arbol(ap.umbrales_disponibles())
    assert arbol["agente"]["tau_ret"] == 0.6 and arbol["cache"]["fichas"]["tau_dup"] == 0.95
    assert arbol["enrutador_fichas"] == {"tau_consenso": 0.7, "tau_acuerdo": 0.3}
    assert "enrutador.json" in arbol["_origen"]["enrutador_fichas.tau_consenso"]
    assert arbol["enrutador_busquedas"] == {"tau_excluir": 0.73}
    assert "calibracion_tau_excluir.json" in arbol["_origen"]["enrutador_busquedas.tau_excluir"]


def test_prototipos_son_todos_texto():
    """Una entrada sin comillas con «: » se lee en YAML como diccionario y rompe el embebido de prototipos."""
    proto = yaml.safe_load((DIR_SERVICIO / "config" / "prototipos.yaml").read_text(encoding="utf-8"))
    listas = [proto["inyeccion"]] + [l for t in ("consulta", "dominio", "texto_visible") for l in proto[t].values()]
    assert all(isinstance(x, str) and x.strip() for l in listas for x in l)


def test_umbral_balanceado_deja_margen_sin_cambiar_tasas():
    from scripts.calibrar import _umbral_balanceado

    positivos = [0.0735, 0.09, 0.12]
    negativos = [-0.05, 0.01, 0.0703]
    r = _umbral_balanceado(positivos, negativos)
    assert r["candidato_en_calibracion"] == 0.0735
    assert r["umbral"] == round((0.0735 + 0.0703) / 2, 4)
    assert all(p >= r["umbral"] for p in positivos) and all(n < r["umbral"] for n in negativos)
    assert (r["tpr"], r["fpr"]) == (1.0, 0.0)
