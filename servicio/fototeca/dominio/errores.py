"""Errores de dominio. La capa de API (C1) los traduce a códigos HTTP; aquí no se conoce HTTP."""
from __future__ import annotations


class ErrorDominio(Exception):
    codigo = "error_interno"

    def __init__(self, mensaje: str, **detalle):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.detalle = detalle


class PeticionInvalida(ErrorDominio):
    codigo = "peticion_invalida"


class NoEncontrado(ErrorDominio):
    codigo = "no_encontrado"


class ArchivoDemasiadoGrande(ErrorDominio):
    codigo = "archivo_demasiado_grande"


class FormatoNoSoportado(ErrorDominio):
    codigo = "formato_no_soportado"


class BloqueadoPorGuardrail(ErrorDominio):
    """Una verificación de entrada bloqueó la petición. `mensaje_seguro` nunca repite el contenido malicioso."""

    codigo = "bloqueado_por_guardrail"

    def __init__(self, mensaje_seguro: str, verificaciones: list[dict] | None = None):
        super().__init__(mensaje_seguro, verificaciones=verificaciones or [])
        self.mensaje_seguro = mensaje_seguro
        self.verificaciones = verificaciones or []


class ServicioNoDisponible(ErrorDominio):
    codigo = "servicio_no_disponible"


class TiempoAgotado(ErrorDominio):
    codigo = "tiempo_agotado"
