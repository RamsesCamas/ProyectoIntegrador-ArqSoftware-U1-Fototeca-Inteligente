"""Tipos de datos que cruzan las fronteras entre capas (los usan los puertos de C7)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

RolMensaje = Literal["system", "user", "assistant"]
RolTexto = Literal["consulta", "documento", "simetrico"]
"""Intención con la que se embebe un texto. El adaptador traduce el rol a los prefijos de su modelo."""


@dataclass(frozen=True)
class Mensaje:
    rol: RolMensaje
    contenido: str


@dataclass(frozen=True)
class OpcionesGeneracion:
    """Muestreo que se envía SIEMPRE explícito: los modelos traen sus propios valores por defecto."""

    temperatura: float = 0.2
    top_p: float = 0.9
    presence_penalty: float = 0.0
    num_ctx: int = 4096
    num_predict: int = 350
    think: bool = False
    extra: dict = field(default_factory=dict)   # opciones propias del servidor (p. ej. draft_num_predict)


@dataclass(frozen=True)
class RespuestaLLM:
    texto: str
    modelo: str
    tokens_prompt: int = 0
    tokens_salida: int = 0
    duracion_total_ms: float = 0.0
    duracion_carga_ms: float = 0.0
    razon_fin: str | None = None
    thinking_eliminado: bool = False


@dataclass(frozen=True)
class ResultadoVectorial:
    id: str
    puntaje: float
    carga: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentoResumen:
    documento_id: str
    tipo: str
    nombre: str
    fecha: str
    estado_ficha: str | None = None
    particion: str | None = None
    titular: str | None = None                 # titular y texto alternativo de la ficha guardada (None si no hay)
    texto_alternativo: str | None = None


@dataclass
class EntradaCache:
    clave: str
    espacio: str
    valor: dict
    creada: float
    expira: float
    etiquetas: list[str] = field(default_factory=list)
    similitud: float | None = None
