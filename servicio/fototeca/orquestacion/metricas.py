"""Métricas y duplicados (C2): combina T1 (eventos), T2 (retroalimentación) y C7 (estado del archivo)."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fototeca.datos.puertos import AlmacenDocumentos
from fototeca.observabilidad.metricas import EVENTOS_CON_DETALLE, agregar
from fototeca.observabilidad.puertos import SumideroEventos
from fototeca.retroalimentacion.servicio import ServicioRetroalimentacion


class FlujoMetricas:
    def __init__(self, sumidero: SumideroEventos, retroalimentacion: ServicioRetroalimentacion,
                 documentos: AlmacenDocumentos):
        self.sumidero = sumidero
        self.retroalimentacion = retroalimentacion
        self.documentos = documentos

    def obtener(self, desde: str | None = None) -> dict:
        """`desde`: instante ISO 8601 en UTC (la API lo normaliza) a partir del cual se cuentan eventos y opiniones.

        Los eventos se leen sin los sondeos de salud y con `detalle` solo de los tipos que usa la agregación."""
        datos = agregar(self.sumidero.consultar_para_metricas(desde=desde, con_detalle=EVENTOS_CON_DETALLE))
        datos["retroalimentacion"] = self.retroalimentacion.resumen(desde)
        datos["accesibilidad"] = self.accesibilidad()     # estado actual del archivo (no depende de `desde`)
        datos["desde"] = desde
        datos["generado"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return datos

    def accesibilidad(self) -> dict:
        """Porcentaje de fotos con texto alternativo validado y de fichas que requieren revisión."""
        e = self.documentos.estadisticas_accesibilidad()
        total = e["fotos"] or 0
        por_estado = self.documentos.contar_fichas()
        return {**e, "fichas_validadas": int(por_estado.get("validada", 0)),
                "porcentaje_alt_validado": round(e["alt_validado"] / total, 4) if total else None,
                "porcentaje_requiere_revision": round(e["requiere_revision"] / total, 4) if total else None,
                "porcentaje_sin_ficha": round(e["sin_ficha"] / total, 4) if total else None}

    def duplicados(self) -> list[dict]:
        """Grupos de casi duplicados: componentes conexas de los pares que la ingesta detectó (similitud ≥ τ_dup).

        Cada documento lleva la mayor similitud con la que entró al grupo y, si tiene ficha, su titular y su texto
        alternativo (la web los usa como `alt` de las miniaturas). El `grupo_id` depende solo de sus miembros.
        """
        pares = self.documentos.listar_duplicados()
        padre: dict[str, str] = {}

        def raiz(x: str) -> str:
            padre.setdefault(x, x)
            while padre[x] != x:
                padre[x] = padre[padre[x]]
                x = padre[x]
            return x

        for p in pares:
            a, b = raiz(p["documento_id"]), raiz(p["similar_a"])
            if a != b:
                padre[b] = a
        grupos: dict[str, dict[str, float]] = {}
        for p in pares:
            g = grupos.setdefault(raiz(p["documento_id"]), {})
            for d in (p["documento_id"], p["similar_a"]):
                g[d] = max(g.get(d, 0.0), float(p["similitud"]))
        salida = []
        for miembros in sorted(grupos.values(), key=lambda m: (-max(m.values()), min(m))):
            documentos = []
            for d, s in sorted(miembros.items(), key=lambda kv: (-kv[1], kv[0])):
                registro = self.documentos.obtener_ficha(d)
                ficha = registro.ficha if registro else None
                documentos.append({"id": d, "similitud": round(s, 4),
                                   "titular": (ficha.titular or None) if ficha else None,
                                   "texto_alternativo": (ficha.texto_alternativo or None) if ficha else None})
            clave = hashlib.sha256("|".join(sorted(miembros)).encode()).hexdigest()[:10]
            salida.append({"grupo_id": f"g-{clave}", "documentos": documentos})
        return salida
