"""C6 · Gateway: plantillas versionadas, reintento por JSON inválido, respaldo y tiempo agotado."""
from __future__ import annotations

import json

import pytest

from fototeca.dominio.errores import TiempoAgotado
from fototeca.modelos.gateway import Gateway, SalidaInvalida
from fototeca.modelos.plantillas import cargar_plantillas, rellenar, versiones
from fototeca.observabilidad.registro import configurar_sumidero


class ClienteGuionado:
    """Cliente LLM falso que responde según un guion por modelo (texto o excepción)."""

    def __init__(self, guion: dict[str, list]):
        self.guion = {m: list(r) for m, r in guion.items()}
        self.llamadas: list[dict] = []

    def generar(self, modelo, mensajes, *, imagenes=None, esquema_json=None, opciones, tiempo_limite_s):
        from fototeca.dominio.entidades import RespuestaLLM
        self.llamadas.append({"modelo": modelo, "mensajes": [m.contenido for m in mensajes], "opciones": opciones,
                              "imagenes": imagenes, "limite": tiempo_limite_s})
        r = self.guion[modelo].pop(0)
        if isinstance(r, Exception):
            raise r
        return RespuestaLLM(texto=r, modelo=modelo, tokens_prompt=10, tokens_salida=5)


@pytest.fixture(autouse=True)
def sin_sumidero():
    configurar_sumidero(None)


@pytest.fixture
def plantillas():
    return cargar_plantillas()


P4_OK = json.dumps({"consulta_semantica": "mercado", "excluir": ["coches"], "contiene_personas": None, "terminos": ["mercado"]})


def test_plantillas_cargan_con_version_y_esquema(plantillas):
    assert {"P1", "P2", "P3", "P4", "P5", "P6"} <= set(plantillas)
    assert plantillas["P1"].version >= 2 and plantillas["P1"].con_imagen
    assert plantillas["P3"].modelo_preferido == "composicion" and plantillas["P3"].modelo_respaldo == "vision"
    assert "P1" in versiones(plantillas)
    # Las llaves literales del prompt P5 se respetan al rellenar
    texto = rellenar(plantillas["P5"].usuario, {"consulta": "perros"})
    assert '"perros"' in texto and '{"reformulaciones"' in texto


def test_reintento_por_json_invalido_agrega_el_error(config, plantillas):
    lfm = config.modelos["composicion"]
    cliente = ClienteGuionado({lfm: ["esto no es json", P4_OK]})
    s = Gateway(cliente, config, plantillas).ejecutar("P4", {"consulta": "mercado sin coches"})
    assert s.datos["excluir"] == ["coches"] and s.intentos == 2 and not s.respaldo
    assert "no cumple el esquema" in cliente.llamadas[1]["mensajes"][-1]


def test_respaldo_cuando_el_primario_agota_intentos(config, plantillas):
    lfm, qwen = config.modelos["composicion"], config.modelos["vision"]
    cliente = ClienteGuionado({lfm: [TiempoAgotado("t"), TiempoAgotado("t")], qwen: [P4_OK]})
    s = Gateway(cliente, config, plantillas).ejecutar("P4", {"consulta": "mercado"})
    assert s.respaldo and s.modelo == qwen


def test_sin_respaldo_y_tiempo_agotado(config, plantillas):
    qwen = config.modelos["vision"]
    cliente = ClienteGuionado({qwen: [TiempoAgotado("t"), TiempoAgotado("t")]})
    with pytest.raises(TiempoAgotado):
        Gateway(cliente, config, plantillas).ejecutar("P1", {}, imagenes=[b"x"])


def test_json_invalido_persistente_sin_respaldo(config, plantillas):
    qwen = config.modelos["vision"]
    cliente = ClienteGuionado({qwen: ["{}", "{}"]})
    with pytest.raises(SalidaInvalida):
        Gateway(cliente, config, plantillas).ejecutar("P6", {"campo": "texto"})


def test_opciones_por_modelo_y_tiempo_limite(config, plantillas):
    qwen = config.modelos["vision"]
    cliente = ClienteGuionado({qwen: [json.dumps({"sensible": False, "fragmentos": []})]})
    Gateway(cliente, config, plantillas).ejecutar("P6", {"campo": "una persona"})
    opciones = cliente.llamadas[0]["opciones"]
    assert opciones.think is False and opciones.temperatura == 0.0
    assert opciones.presence_penalty == config.parametro("generacion.por_modelo")[qwen]["presence_penalty"]
    assert opciones.extra.get("draft_num_predict") == 0
    assert cliente.llamadas[0]["imagenes"] is None   # P6 es solo texto
