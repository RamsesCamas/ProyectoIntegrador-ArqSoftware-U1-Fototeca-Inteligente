"""Catalogación por lotes, asíncrona (C2; ADR-08).

Un solo trabajador en segundo plano (`ThreadPoolExecutor(max_workers=1)`) procesa **una ficha a la vez**, en
coherencia con `OLLAMA_NUM_PARALLEL=1`. El estado vive en SQLite (`AlmacenLotes`), así que el progreso se puede
consultar desde la API y un lote interrumpido por un reinicio se reanuda al arrancar. Sin Celery ni Redis.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fototeca.datos.puertos import AlmacenLotes
from fototeca.dominio.errores import ErrorDominio, NoEncontrado
from fototeca.observabilidad.registro import registrar
from fototeca.observabilidad.traza import fijar_traza, nueva_traza, restaurar_traza
from fototeca.orquestacion.flujo_ficha import FlujoFicha, OpcionesFicha


class GestorLotes:
    def __init__(self, flujo: FlujoFicha, almacen: AlmacenLotes):
        self.flujo = flujo
        self.almacen = almacen
        self._ejecutor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lote")

    def crear(self, documento_ids: list[str], opciones: OpcionesFicha | None = None) -> str:
        lote_id = self.almacen.crear(documento_ids, vars(opciones) if opciones else {})
        registrar("C2", "lote_creado", lote_id=lote_id, total=len(documento_ids))
        self._ejecutor.submit(self._procesar, lote_id)
        return lote_id

    def reanudar_pendientes(self) -> None:
        for lote_id in self.almacen.pendientes():
            self._ejecutor.submit(self._procesar, lote_id)

    def _procesar(self, lote_id: str) -> None:
        lote = self.almacen.obtener(lote_id)
        if lote is None:
            return
        self.almacen.marcar_lote(lote_id, "en_proceso")
        opciones = OpcionesFicha(**lote["opciones"]) if lote["opciones"] else None
        for item in lote["items"]:
            if item["estado"] in ("completada", "fallida"):
                continue
            token = fijar_traza(None)
            traza = nueva_traza()
            try:
                self.almacen.marcar_item(lote_id, item["posicion"], "en_proceso", traza_id=traza)
                respuesta = self.flujo.ejecutar(item["documento_id"], opciones)
                self.almacen.marcar_item(lote_id, item["posicion"], "completada", respuesta=respuesta, traza_id=traza)
            except ErrorDominio as e:
                self.almacen.marcar_item(lote_id, item["posicion"], "fallida", error=getattr(e, "mensaje_seguro", e.mensaje),
                                         traza_id=traza)
            except Exception as e:  # noqa: BLE001 — un error inesperado no detiene el resto del lote
                self.almacen.marcar_item(lote_id, item["posicion"], "fallida", error=f"Error interno: {type(e).__name__}",
                                         traza_id=traza)
                registrar("C2", "lote_error", lote_id=lote_id, documento_id=item["documento_id"], error=type(e).__name__)
            finally:
                restaurar_traza(token)
        self.almacen.marcar_lote(lote_id, "terminado")
        registrar("C2", "lote_terminado", lote_id=lote_id)

    def obtener(self, lote_id: str) -> dict:
        lote = self.almacen.obtener(lote_id)
        if lote is None:
            raise NoEncontrado("El lote no existe.", lote_id=lote_id)
        items = lote["items"]
        return {
            "lote_id": lote_id, "estado": lote["estado"], "total": len(items),
            "completadas": sum(1 for i in items if i["estado"] == "completada"),
            "fallidas": sum(1 for i in items if i["estado"] == "fallida"),
            "en_proceso": next((i["documento_id"] for i in items if i["estado"] == "en_proceso"), None),
            "fichas": [i["respuesta"] for i in items if i["respuesta"]],
            "errores": [{"documento_id": i["documento_id"], "mensaje": i["error"], "traza_id": i["traza_id"]}
                        for i in items if i["estado"] == "fallida"],
        }
