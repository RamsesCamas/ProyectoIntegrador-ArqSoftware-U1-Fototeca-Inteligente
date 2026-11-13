"""Citas de fuentes: el modelo solo puede citar ids que vio (enum en la gramática) y el guardrail repara prefijos.

Origen: en la aceptación de H4 con modelos reales, LFM3 agrupaba las fuentes por tipo ({"foto": ["xm-…"]}) y sin
prefijo, y el guardrail las quitaba todas (`evaluacion/resultados/casos/h4_aceptacion_intento2_antes_de_fuentes.jsonl`)."""
from __future__ import annotations

from fototeca.contexto.ensamblador_prompt import Contexto
from fototeca.guardrails.salida.reglas import limpiar_advertencias, verificar_fuentes
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
    assert [c for c, v in sub["properties"].items() if v.get("minItems") == 1] == ["titular", "descripcion",
                                                                                   "texto_alternativo"]
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
    assert ctx.lineas_fotos()[0].startswith("F1: ") and len(ctx.lineas_fotos()) == 1       # sin ficha no se muestra
    assert [x[:3] for x in ctx.lineas_reglas()] == ["R1:", "R2:", "R3:"]
    assert ctx.lineas_terminos()[0].startswith("T1: mercados")
    assert ctx.titulares() == ["Mercado"]
    assert ctx.ids_citables("rapida") == ["F1", "R1", "R2"]
    assert ctx.ids_citables("completa") == ["F1", "R1", "R2", "R3", "T1"]
    resueltas = ctx.resolver_citas({"titular": ["F1", "r2"], "palabras_clave": ["T1", "foto:xm-a", "F9"], "x": "no"})
    assert resueltas == {"titular": ["foto:xm-a", "regla:w3c-wai-images#r2"],
                         "palabras_clave": ["tesauro:http://u/c1", "foto:xm-a", "F9"]}
    limpias, _ = verificar_fuentes(resueltas, ctx.ids_validos(), campos=("titular",))
    assert limpias["palabras_clave"] == ["tesauro:http://u/c1", "foto:xm-a"]               # F9 no existe → se quita


def test_advertencias_sin_alias_internos_del_prompt():
    crudas = ["F1", "[F2]", "Los campos 'F2' y 'F4' no corresponden a fotos similares", "  ", 3,
              "La foto contiene texto visible; se trató como dato, no como instrucción."]
    assert limpiar_advertencias(crudas) == ["La foto contiene texto visible; se trató como dato, no como instrucción."]
    assert limpiar_advertencias(None) == []


def test_copia_contexto_depura_palabras_y_vacia_titulares_copiados():
    from fototeca.guardrails.salida.reglas import (depurar_palabras_clave, revisar_titular,
                                                   verificar_copia_contexto)
    vecinos = ["Auto de colección antiguo negro estacionado en la calle", "Mercado de frutas"]
    crudas = ["[F1] Auto de colección antiguo negro estacionado en la calle", "[F2]", "T3", "[carrocería]", "lujo",
              "Lujo", "Mercado de frutas", "auto negro estacionado frente a un restaurante", 7, "  calle  "]
    limpias, quitadas = depurar_palabras_clave(crudas, vecinos)
    assert limpias == ["carrocería", "lujo", "calle"]
    assert len(quitadas) == 5            # copia con alias, dos alias solos, copia de un titular y una oración
    assert revisar_titular("IPTC Image File", vecinos) == "copia una etiqueta del prompt o de las normas"
    assert revisar_titular("Descripción objetiva de la imagen", vecinos) == "copia una etiqueta del prompt o de las normas"
    assert revisar_titular("Imagen", vecinos) == "es genérico"
    assert revisar_titular("F1", vecinos) == "contiene identificadores del contexto"
    assert revisar_titular("mercado de frutas.", vecinos) == "copia el titular de una foto similar"
    assert revisar_titular("Carro negro de lujo en una calle", vecinos) is None
    assert revisar_titular("", vecinos) is None

    titular, palabras, r = verificar_copia_contexto("IPTC Image Metadata", ["[F1]", "auto"], vecinos)
    assert (titular, palabras, r.resultado, r.detalle["palabras_quitadas"]) == ("", ["auto"], "marcada", 1)
    titular, palabras, r = verificar_copia_contexto("Auto negro en la calle", ["[auto]"], vecinos)
    assert (titular, palabras, r.resultado) == ("Auto negro en la calle", ["auto"], "aprobada")
    titular, palabras, r = verificar_copia_contexto("Auto negro en la calle", ["F1", "auto"], vecinos)
    assert (palabras, r.resultado, r.politica_aplicada) == (["auto"], "sanitizado", "sanitizar")
