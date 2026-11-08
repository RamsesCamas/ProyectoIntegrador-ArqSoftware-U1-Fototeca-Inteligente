"""Servicio de retroalimentación (T2): persiste la opinión ligada a la traza, emite el evento y resume.

La promoción de una ficha validada como ejemplo del RAG la orquesta C2 (`orquestacion/retroalimentacion.py`);
aquí solo se guarda y se resume, para que T2 no dependa de ninguna capa de negocio.
"""
from __future__ import annotations

from collections import defaultdict

from fototeca.observabilidad.registro import registrar
from fototeca.retroalimentacion.puertos import AlmacenRetroalimentacion, RegistroRetroalimentacion


class ServicioRetroalimentacion:
    def __init__(self, almacen: AlmacenRetroalimentacion):
        self.almacen = almacen

    def guardar(self, registro: RegistroRetroalimentacion) -> int:
        identificador = self.almacen.guardar(registro)
        registrar("T2", "retroalimentacion", ruta=registro.ruta, resultado="util" if registro.util else
                  ("no_util" if registro.util is False else "sin_calificar"), traza_referida=registro.traza_id,
                  documento_id=registro.documento_id, validar_ficha=registro.validar_ficha,
                  campos_corregidos=sorted(registro.correcciones or {}))
        return identificador

    def resumen(self, desde: str | None = None) -> dict:
        registros = self.almacen.listar(desde)
        por_ruta: dict[str, dict[str, int]] = defaultdict(lambda: {"util": 0, "no_util": 0})
        por_modelo: dict[str, dict[str, int]] = defaultdict(lambda: {"util": 0, "no_util": 0})
        for r in registros:
            if r.util is None:
                continue
            clave = "util" if r.util else "no_util"
            por_ruta[r.ruta or "desconocida"][clave] += 1
            for modelo in sorted(set((r.modelos or {}).values())):
                por_modelo[modelo][clave] += 1
        calificados = [r for r in registros if r.util is not None]
        return {
            "total": len(registros), "util": sum(1 for r in calificados if r.util),
            "no_util": sum(1 for r in calificados if not r.util),
            "tasa_util": round(sum(1 for r in calificados if r.util) / len(calificados), 4) if calificados else None,
            "con_comentario": sum(1 for r in registros if r.comentario),
            "fichas_validadas": sum(1 for r in registros if r.validar_ficha),
            "campos_corregidos": dict(sorted(_contar_campos(registros).items())),
            "por_ruta": dict(por_ruta), "por_modelo": dict(por_modelo),
        }


def _contar_campos(registros: list[RegistroRetroalimentacion]) -> dict[str, int]:
    conteo: dict[str, int] = defaultdict(int)
    for r in registros:
        for campo in (r.correcciones or {}):
            conteo[campo] += 1
    return conteo
