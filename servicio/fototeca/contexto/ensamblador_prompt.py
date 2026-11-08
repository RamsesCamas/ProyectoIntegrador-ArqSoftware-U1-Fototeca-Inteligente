"""Armado del prompt (C5): ids estables y presupuesto de tokens (informe, §8.1).

- Cada elemento del contexto lleva un id estable: `foto:xm-…`, `regla:iptc-2025.1#…`, `tesauro:<uri>`. El modelo
  debe citar solo esos ids y el guardrail `fuentes` (C3) lo verifica.
- Presupuesto para LFM3: 2,000 tokens o menos, estimados como caracteres / 3.5. Si no cabe, se recorta en este
  orden: (1) las fichas vecinas, de la menos a la más similar; (2) la descripción extendida de los vecinos (no
  se incluye en estas líneas, así que no aplica); (3) las reglas, de la de menor a la de mayor puntaje. Se
  conservan al menos 2 vecinos y 1 regla mientras sea posible.
- Modo `sin_rag` (solo evaluación): no se entregan vecinos, reglas ni términos.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fototeca.contexto.recuperador_ejemplos import Vecino
from fototeca.dominio.entidades import ResultadoVectorial


def id_foto(documento_id: str) -> str:
    return f"foto:{documento_id}"


def id_regla(r: ResultadoVectorial) -> str:
    return f"regla:{r.id}"


def id_tesauro(r: ResultadoVectorial) -> str:
    return f"tesauro:{r.carga.get('uri', r.id)}"


def _corto(texto: str | None, n: int) -> str:
    texto = " ".join((texto or "").split())
    return texto if len(texto) <= n else texto[:n - 1].rstrip() + "…"


@dataclass
class Contexto:
    vecinos: list[Vecino] = field(default_factory=list)
    reglas: list[ResultadoVectorial] = field(default_factory=list)
    terminos: list[ResultadoVectorial] = field(default_factory=list)
    sin_rag: bool = False
    recortes: list[str] = field(default_factory=list)

    def ids_validos(self) -> set[str]:
        return ({id_foto(v.documento_id) for v in self.vecinos} | {id_regla(r) for r in self.reglas}
                | {id_tesauro(t) for t in self.terminos})

    # ── líneas por tipo ──
    def lineas_fotos(self, estilo: str = "completa") -> list[str]:
        lineas = []
        for v in self.vecinos:
            f = v.ficha.ficha if v.ficha else None
            if f is None:
                continue
            palabras = ", ".join(p.termino for p in f.palabras_clave[:8])
            if estilo == "rapida":
                lineas.append(f"[{id_foto(v.documento_id)}] titular: {_corto(f.titular, 120)} | texto_alternativo: "
                              f"{_corto(f.texto_alternativo, 250)} | palabras_clave: {palabras}")
            else:
                lineas.append(f"[{id_foto(v.documento_id)}] {_corto(f.titular, 120)} | {_corto(f.descripcion, 300)} | {palabras}")
        return lineas

    def lineas_reglas(self) -> list[str]:
        return [f"[{id_regla(r)}] {_corto(r.carga.get('texto', ''), 600)}" for r in self.reglas]

    def lineas_terminos(self) -> list[str]:
        return [f"[{id_tesauro(t)}] {t.carga.get('etiqueta_es', '')} — {_corto(t.carga.get('nota_alcance', ''), 120)}"
                for t in self.terminos]


def _tokens(texto: str, caracteres_por_token: float) -> int:
    return int(len(texto) / caracteres_por_token) + 1


def variables_p3(p1: dict, ctx: Contexto, sistema: str, presupuesto: int = 2000,
                 caracteres_por_token: float = 3.5) -> dict:
    """Variables de la plantilla P3, recortando el contexto hasta que quepa en el presupuesto."""
    if ctx.sin_rag:
        ctx = Contexto(sin_rag=True)

    def armar() -> dict:
        return {
            "descripcion_visual": p1.get("descripcion_visual", ""),
            "elementos": ", ".join(p1.get("elementos", [])),
            "texto_visible": " | ".join(p1.get("texto_visible", [])),
            "fotos_similares": "\n".join(ctx.lineas_fotos("completa")) or "(ninguna)",
            "reglas": "\n".join(ctx.lineas_reglas()) or "(ninguna)",
            "terminos": "\n".join(ctx.lineas_terminos()) or "(ninguno)",
        }

    variables = armar()
    while _tokens(sistema + "".join(map(str, variables.values())), caracteres_por_token) > presupuesto:
        if len(ctx.vecinos) > 2:
            quitado = min(ctx.vecinos, key=lambda v: v.similitud_imagen)
            ctx.vecinos.remove(quitado)
            ctx.recortes.append(f"vecino {quitado.documento_id}")
        elif len(ctx.reglas) > 1:
            quitada = min(ctx.reglas, key=lambda r: r.puntaje)
            ctx.reglas.remove(quitada)
            ctx.recortes.append(f"regla {quitada.id}")
        elif ctx.vecinos:
            ctx.recortes.append(f"vecino {ctx.vecinos.pop().documento_id}")
        elif ctx.reglas:
            ctx.recortes.append(f"regla {ctx.reglas.pop().id}")
        else:
            break
        variables = armar()
    return variables


def variables_p2(ctx: Contexto) -> dict:
    """Contexto de la ruta rápida: fichas vecinas y, si hay, las reglas más pertinentes (ids citables)."""
    if ctx.sin_rag:
        return {"contexto": "(sin contexto)"}
    lineas = ctx.lineas_fotos("rapida") + ctx.lineas_reglas()[:2]
    return {"contexto": "\n".join(lineas) or "(ninguna)"}
