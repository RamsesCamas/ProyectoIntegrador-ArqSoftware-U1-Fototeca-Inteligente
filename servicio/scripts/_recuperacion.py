"""Recuperación de ejemplos para fotos de XM3600 sin subirlas (vectores de imagen ya calculados en H2).

La usan `verificar_h4` y `preparar_demo` para elegir, de `regiones_excluidas`, fotos cuya recuperación es pobre según
la MISMA regla del flujo (`recuperacion_pobre`): así el caso del ciclo de agente lo es por construcción y no por azar.
"""
from __future__ import annotations

import numpy as np

from fototeca.contexto.recuperador_ejemplos import RecuperadorEjemplos
from fototeca.guardrails.entrada.imagen import VerificadorImagen
from fototeca.orquestacion.flujo_ficha import recuperacion_pobre
from scripts.preparar_datos import PROCESADOS, slug


def matriz_imagenes(c) -> tuple[dict, np.ndarray]:
    p = c.embebedor
    z = np.load(PROCESADOS / f"emb_img_{slug(p.nombre_modelo)}_{p.lado_imagen_px}px.npz", allow_pickle=False)
    return {k: i for i, k in enumerate(z["ids"].tolist())}, z["vectores"]


def recuperacion_de(c, fotos: list[str]) -> list[dict]:
    """Por foto (`xm-…`), en el orden recibido: top-1, margen, si la recuperación sería pobre, y las diferencias que
    usan los guardrails de entrada (`dominio`: foto − documento; `texto_visible`: con texto − sin texto)."""
    indice, m = matriz_imagenes(c)
    rec = RecuperadorEjemplos(c.almacen_vectorial, c.embebedor, c.almacen_documentos)
    ver = VerificadorImagen(c.config, c.almacen_vectorial, c.embebedor)
    salida = []
    for xm in fotos:
        v = m[indice[xm.removeprefix("xm-")]]
        r = rec.fusionar(v, rec.listas_unificadas(v, xm))
        salida.append({"xm": xm, "top1": round(float(r.top1), 4), "margen": round(float(r.margen), 4),
                       "pobre": recuperacion_pobre(c.config, r.top1, r.margen),
                       "dominio": round(float(ver._diferencia(v, "dominio", "fotografia", "fuera_de_dominio")), 4),
                       "texto_visible": round(float(ver._diferencia(v, "texto_visible", "con_texto", "sin_texto")), 4)})
    return salida


def foto_clara(c, x: dict, holgura: float = 0.03) -> bool:
    """Lejos del umbral de fuera de dominio y sin texto visible: el caso muestra el ciclo de agente y no otro camino."""
    tau_fd = float(c.config.parametro("guardrails.tau_fuera_dominio", 0.0) or 0.0)
    tau_tv = float(c.config.parametro("guardrails.tau_texto_visible", 1.0) or 1.0)
    return x["dominio"] >= tau_fd + holgura and x["texto_visible"] < tau_tv
