"""Gateway de modelos (C6): interfaz única `ejecutar(tarea, variables, imagenes)` hacia todos los modelos.

- Tabla de tareas: cada prompt (P1–P6) declara su modelo preferido, su respaldo, su `num_predict` y su esquema.
- Tiempo límite por modelo y tipo de entrada (`tiempos_limite_s`, calibrados en H0 como 1.5 × p95).
- Reintentos: 1 ante error de transporte o JSON inválido, con 1 s de espera. En el reintento por JSON inválido se
  agrega al prompt el error del validador.
- Cadena de respaldo: si el modelo preferido agota sus intentos, se usa el de respaldo (P3: LFM3 → Qwen;
  P4/P5: LFM3 → Qwen). El «último recurso» de cada tarea lo decide la orquestación (C2).
- Registro de uso en T1: modelo, tarea, tokens, duraciones, si se agotó el tiempo y si se usó el respaldo.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from fototeca.datos.puertos import ClienteLLM
from fototeca.dominio.configuracion import Configuracion
from fototeca.dominio.entidades import Mensaje, OpcionesGeneracion
from fototeca.dominio.errores import ServicioNoDisponible, TiempoAgotado
from fototeca.modelos.plantillas import Plantilla
from fototeca.modelos.validacion import extraer_json, validar
from fototeca.observabilidad.registro import registrar


class SalidaInvalida(ServicioNoDisponible):
    """El modelo respondió, pero su JSON no cumple el esquema tras los reintentos."""

    codigo = "salida_invalida"


@dataclass
class SalidaTarea:
    tarea: str
    datos: dict
    modelo: str
    respaldo: bool = False
    intentos: int = 1
    tokens_prompt: int = 0
    tokens_salida: int = 0
    duracion_ms: float = 0.0
    errores_previos: list[str] = field(default_factory=list)


class Gateway:
    def __init__(self, cliente: ClienteLLM, config: Configuracion, plantillas: dict[str, Plantilla]):
        self.cliente = cliente
        self.config = config
        self.plantillas = plantillas

    # ── configuración por modelo ──
    def opciones(self, plantilla: Plantilla, modelo: str) -> OpcionesGeneracion:
        g = self.config.parametro
        por_modelo = (g("generacion.por_modelo", {}) or {}).get(modelo, {})
        return OpcionesGeneracion(
            temperatura=plantilla.temperatura, top_p=float(g("generacion.top_p", 0.9)),
            presence_penalty=float(por_modelo.get("presence_penalty", g("generacion.presence_penalty", 0.0))),
            num_ctx=int(g("generacion.num_ctx", 4096)), num_predict=plantilla.num_predict,
            think=bool(g("generacion.think", False)), extra=dict(por_modelo.get("extra", {})))

    def tiempo_limite(self, plantilla: Plantilla, rol: str) -> float:
        t = self.config.parametro("tiempos_limite_s", {}) or {}
        if rol == "vision":
            return float(t.get("qwen_imagen" if plantilla.con_imagen else "qwen_texto", 60))
        return float(t.get("lfm3", 90))

    # ── ejecución ──
    def ejecutar(self, tarea: str, variables: dict, imagenes: list[bytes] | None = None, *,
                 rol: str | None = None, permitir_respaldo: bool = True,
                 esquema_gramatica: dict | None = None) -> SalidaTarea:
        """`esquema_gramatica` (opcional) es el esquema que se envía al modelo para restringir su salida; la respuesta
        se valida siempre contra el esquema estático de la plantilla."""
        plantilla = self.plantillas[tarea]
        gramatica = esquema_gramatica or plantilla.esquema
        cadena = [rol] if rol else [plantilla.modelo_preferido] + (
            [plantilla.modelo_respaldo] if permitir_respaldo and plantilla.modelo_respaldo else [])
        espera = float(self.config.parametro("gateway.espera_reintento_s", 1))
        reintentos = int(self.config.parametro("gateway.reintentos", 1))
        errores_previos: list[str] = []
        ultimo: Exception | None = None
        for posicion, rol_modelo in enumerate(cadena):
            modelo = self.config.modelos[rol_modelo]
            mensajes = plantilla.mensajes(variables)
            con_imagen = imagenes if (plantilla.con_imagen and rol_modelo == "vision") else None
            for intento in range(1, reintentos + 2):
                t0 = time.perf_counter()
                comun = {"modelo": modelo, "tarea": tarea, "intento": intento, "respaldo": posicion > 0}
                try:
                    resp = self.cliente.generar(modelo, mensajes, imagenes=con_imagen, esquema_json=gramatica,
                                                opciones=self.opciones(plantilla, modelo),
                                                tiempo_limite_s=self.tiempo_limite(plantilla, rol_modelo))
                except (TiempoAgotado, ServicioNoDisponible) as e:
                    registrar("C6", "llamada_modelo", duracion_ms=(time.perf_counter() - t0) * 1000,
                              resultado="tiempo_agotado" if isinstance(e, TiempoAgotado) else "error_transporte",
                              tiempo_agotado=isinstance(e, TiempoAgotado), **comun)
                    ultimo = e
                    errores_previos.append(f"{modelo}: {type(e).__name__}")
                    time.sleep(espera)
                    continue
                datos, errores = extraer_json(resp.texto)
                if datos is not None:
                    errores = validar(datos, plantilla.esquema)
                registrar("C6", "llamada_modelo", duracion_ms=(time.perf_counter() - t0) * 1000,
                          resultado="ok" if not errores else "json_invalido", tokens_prompt=resp.tokens_prompt,
                          tokens_salida=resp.tokens_salida, carga_ms=round(resp.duracion_carga_ms, 1),
                          razon_fin=resp.razon_fin, thinking_eliminado=resp.thinking_eliminado,
                          tiempo_agotado=False, **comun,
                          # Para diagnosticar (p. ej. repeticiones hasta el límite de tokens): solo si es inválido.
                          **({"errores": errores[:3], "cola_texto": (resp.texto or "")[-300:]} if errores else {}))
                if not errores:
                    return SalidaTarea(tarea, datos, modelo, respaldo=posicion > 0, intentos=intento,
                                       tokens_prompt=resp.tokens_prompt, tokens_salida=resp.tokens_salida,
                                       duracion_ms=resp.duracion_total_ms, errores_previos=errores_previos)
                errores_previos += errores[:3]
                ultimo = SalidaInvalida("El modelo no produjo un JSON válido", errores=errores[:5])
                mensajes = plantilla.mensajes(variables) + [
                    Mensaje("assistant", (resp.texto or "")[:1500]),
                    Mensaje("user", "Tu respuesta no cumple el esquema: " + "; ".join(errores[:3]) +
                            ". Responde de nuevo solo con el JSON corregido.")]
                time.sleep(espera)
        if isinstance(ultimo, TiempoAgotado):
            raise TiempoAgotado(f"La tarea {tarea} agotó el tiempo límite y la cadena de respaldo",
                                errores=errores_previos)
        raise ultimo if ultimo else ServicioNoDisponible(f"No hay modelo disponible para {tarea}")
