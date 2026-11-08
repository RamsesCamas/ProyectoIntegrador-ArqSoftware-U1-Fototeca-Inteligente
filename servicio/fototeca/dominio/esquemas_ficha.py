"""Esquema de la ficha catalográfica IPTC (docs/specs/03-api.md) y de sus fuentes."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EstadoFicha = Literal["borrador", "validada", "requiere_revision"]
TipoFuente = Literal["regla", "foto_similar", "tesauro", "referencia_humana", "etiqueta_open_images", "archivista"]
"""`referencia_humana` y `etiqueta_open_images` solo aparecen en las fichas iniciales del archivo (sin modelos);
`archivista` en los campos corregidos por la persona al validar."""
OrigenPalabra = Literal["tesauro", "libre"]


class PalabraClave(BaseModel):
    termino: str
    uri: str | None = None
    origen: OrigenPalabra = "libre"
    similitud: float | None = None


class Fuente(BaseModel):
    """De dónde salió un campo: una regla normativa, una foto similar ya catalogada o un término del tesauro."""

    tipo: TipoFuente
    id: str
    titulo: str | None = None
    puntaje: float | None = None


class Ficha(BaseModel):
    titular: str = Field("", max_length=120)
    descripcion: str = Field("", max_length=800)
    texto_alternativo: str = Field("", max_length=250, description="IPTC Alt Text (Accessibility): 250 caracteres o menos")
    descripcion_extendida: str = Field("", max_length=1200)
    palabras_clave: list[PalabraClave] = Field(default_factory=list)
    advertencias: list[str] = Field(default_factory=list)
    estado: EstadoFicha = "borrador"


class FichaRegistrada(BaseModel):
    """Lo que se guarda por documento: la ficha, sus fuentes por campo y metadatos mínimos de origen."""

    documento_id: str
    ficha: Ficha
    fuentes: dict[str, list[Fuente]] = Field(default_factory=dict)
    origen: str = "modelo"           # modelo | referencia_humana | archivista
    traza_id: str | None = None
    actualizada: str | None = None
