"""Citas de fuentes: el modelo solo puede citar ids que vio (enum en la gramática) y el guardrail repara prefijos.

Origen: en la aceptación de H4 con modelos reales, LFM3 agrupaba las fuentes por tipo ({"foto": ["xm-…"]}) y sin
prefijo, y el guardrail las quitaba todas (`evaluacion/resultados/casos/h4_aceptacion_intento2_antes_de_fuentes.jsonl`)."""
from __future__ import annotations

from fototeca.contexto.ensamblador_prompt import Contexto
from fototeca.guardrails.salida.reglas import verificar_fuentes
from fototeca.modelos.plantillas import cargar_plantillas, esquema_con_fuentes
from fototeca.modelos.validacion import validar


def test_esquemas_p2_p3_fijan_las_claves_de_fuentes_por_campo():
    pl = cargar_plantillas()
    for tarea, campos in (("P2", {"titular", "texto_alternativo", "palabras_clave"}),
                          ("P3", {"titular", "descripcion", "texto_alternativo", "palabras_clave"})):
        fuentes = pl[tarea].esquema["properties"]["fuentes"]
        assert fuentes["additionalProperties"] is False and set(fuentes["properties"]) == campos
        # Agrupar por tipo, como hacía LFM3, ya no cumple el esquema estático
        assert validar({"foto": ["foto:xm-a"]}, fuentes)


def test_gramatica_restringe_las_citas_a_los_ids_del_prompt():
    esquema = cargar_plantillas()["P3"].esquema
    g = esquema_con_fuentes(esquema, ["foto:xm-a", "regla:iptc#alt", "foto:xm-a"])
    sub = g["properties"]["fuentes"]
    assert sub["required"] == list(sub["properties"])
    assert sub["properties"]["titular"]["items"]["enum"] == ["foto:xm-a", "regla:iptc#alt"]
    assert "enum" not in str(esquema["properties"]["fuentes"])            # el estático no se modifica
    assert validar({"titular": ["foto:otra"]}, sub)                          # fuera del enum → inválido
    sin_ids = esquema_con_fuentes(esquema, [])["properties"]["fuentes"]["properties"]
    assert all(v["maxItems"] == 0 for v in sin_ids.values())


def test_ids_citables_son_los_del_prompt_de_cada_ruta():
    assert Contexto(sin_rag=True).ids_citables("completa") == []
    assert Contexto().ids_citables("rapida") == []


def test_guardrail_repara_un_id_sin_prefijo_solo_si_es_inequivoco():
    validos = {"foto:xm-a", "regla:iptc#alt", "tesauro:x", "regla:x"}
    limpias, r = verificar_fuentes({"titular": ["xm-a"], "texto_alternativo": ["iptc#alt", "x", "inventada"]}, validos,
                                   campos=("titular", "texto_alternativo"))
    assert limpias == {"titular": ["foto:xm-a"], "texto_alternativo": ["regla:iptc#alt"]}
    assert r.resultado == "sanitizado" and r.detalle["invalidas_quitadas"] == 2     # «x» es ambiguo, «inventada» no existe


def _contexto_de_prueba() -> Contexto:
    from fototeca.dominio.entidades import ResultadoVectorial
    from fototeca.contexto.recuperador_ejemplos import Vecino
    from fototeca.dominio.esquemas_ficha import Ficha, FichaRegistrada

    ficha = FichaRegistrada(documento_id="xm-a", ficha=Ficha(titular="Mercado", descripcion="Puesto de frutas",
                                                             texto_alternativo="Puesto de frutas."))
    vecinos = [Vecino(documento_id="xm-a", puntaje_rrf=0.03, similitud_imagen=0.8, ficha=ficha),
               Vecino(documento_id="xm-sin-ficha", puntaje_rrf=0.02, similitud_imagen=0.7, ficha=None)]
    reglas = [ResultadoVectorial(id=f"w3c-wai-images#r{i}", puntaje=0.5, carga={"texto": f"regla {i}"}) for i in (1, 2, 3)]
    terminos = [ResultadoVectorial(id="t", puntaje=0.9, carga={"uri": "http://u/c1", "etiqueta_es": "mercados"})]
    return Contexto(vecinos=vecinos, reglas=reglas, terminos=terminos)


def test_alias_cortos_en_el_prompt_y_su_traduccion():
    ctx = _contexto_de_prueba()
    assert ctx.lineas_fotos()[0].startswith("[F1] ") and len(ctx.lineas_fotos()) == 1      # sin ficha no se muestra
    assert [x[:4] for x in ctx.lineas_reglas()] == ["[R1]", "[R2]", "[R3]"]
    assert ctx.lineas_terminos()[0].startswith("[T1] mercados")
    assert ctx.ids_citables("rapida") == ["F1", "R1", "R2"]
    assert ctx.ids_citables("completa") == ["F1", "R1", "R2", "R3", "T1"]
    resueltas = ctx.resolver_citas({"titular": ["F1", "r2"], "palabras_clave": ["T1", "foto:xm-a", "F9"], "x": "no"})
    assert resueltas == {"titular": ["foto:xm-a", "regla:w3c-wai-images#r2"],
                         "palabras_clave": ["tesauro:http://u/c1", "foto:xm-a", "F9"]}
    limpias, _ = verificar_fuentes(resueltas, ctx.ids_validos(), campos=("titular",))
    assert limpias["palabras_clave"] == ["tesauro:http://u/c1", "foto:xm-a"]               # F9 no existe → se quita
