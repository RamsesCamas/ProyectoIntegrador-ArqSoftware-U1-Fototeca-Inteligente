"""Adaptador de Ollama para el puerto `Embebedor` (C7).

- EmbeddingGemma-2 pone textos e imágenes en un mismo espacio de 768 dimensiones (H0: tag `440m`, el más
  pequeño con visión; sus embeddings de texto son idénticos a los de `270m`, coseno 1.0 — ADR-10).
- Los prefijos de tarea dependen del modelo; las capas superiores solo indican el `rol` del texto.
- Las imágenes viajan como JPEG en base64 dentro de `input` (`/api/embed` de Ollama 0.40.15), reducidas al
  lado máximo calibrado en H0 (verificación 0.3b).
- Todos los vectores se devuelven normalizados L2.
"""
from __future__ import annotations

import base64

import httpx
import numpy as np

from fototeca.datos.imagenes import preparar_imagen
from fototeca.dominio.entidades import RolTexto
from fototeca.dominio.errores import ServicioNoDisponible, TiempoAgotado


def normalizar(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    if m.ndim == 1:
        m = m[None, :]
    return m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-12, None)


class EmbebedorOllama:
    def __init__(self, url: str, modelo: str, *, prefijos: dict[str, str] | None = None,
                 acepta_imagenes: bool = False, lado_imagen_px: int = 768, lote: int = 8,
                 tiempo_limite_s: float = 30.0, keep_alive: int | str = -1):
        self.nombre_modelo = modelo
        self.prefijos = dict(prefijos or {})
        self.acepta_imagenes = acepta_imagenes
        self.lado_imagen_px = int(lado_imagen_px)
        self.lote = max(1, int(lote))
        self.tiempo_limite_s = float(tiempo_limite_s)
        self.keep_alive = keep_alive
        self._dimension: int | None = None
        self._http = httpx.Client(base_url=url.rstrip("/"), timeout=httpx.Timeout(10.0, read=600.0))

    @property
    def dimension(self) -> int:
        """Se toma de la respuesta real del modelo (02 §3: no se escribe a mano)."""
        if self._dimension is None:
            self._dimension = int(self._embeber(["dimension"]).shape[1])
        return self._dimension

    def embeber_textos(self, textos: list[str], rol: RolTexto = "documento") -> np.ndarray:
        if not textos:
            return np.zeros((0, self.dimension), dtype=np.float32)
        prefijo = self.prefijos.get(rol, "")
        return self._embeber([prefijo + (t or "") for t in textos])

    def embeber_imagenes(self, imagenes: list[bytes]) -> np.ndarray:
        if not self.acepta_imagenes:
            raise NotImplementedError(f"{self.nombre_modelo} solo embebe texto")
        if not imagenes:
            return np.zeros((0, self.dimension), dtype=np.float32)
        entradas = [{"image": base64.b64encode(preparar_imagen(b, self.lado_imagen_px)).decode("ascii")}
                    for b in imagenes]
        return self._embeber(entradas)

    def _embeber(self, entradas: list) -> np.ndarray:
        vectores: list[list[float]] = []
        for i in range(0, len(entradas), self.lote):
            parte = entradas[i:i + self.lote]
            limite = self.tiempo_limite_s * len(parte)
            try:
                r = self._http.post("/api/embed", json={"model": self.nombre_modelo, "input": parte,
                                                        "keep_alive": self.keep_alive, "truncate": True},
                                    timeout=httpx.Timeout(10.0, read=limite))
            except httpx.TimeoutException as e:
                raise TiempoAgotado(f"El modelo {self.nombre_modelo} no respondió en {limite:.0f} s") from e
            except httpx.HTTPError as e:
                raise ServicioNoDisponible(f"No se pudo contactar al servidor de modelos: {type(e).__name__}") from e
            if r.status_code >= 400:
                raise ServicioNoDisponible(f"Error del modelo {self.nombre_modelo}: {r.text[:200]}")
            vectores += r.json()["embeddings"]
        m = normalizar(np.asarray(vectores, dtype=np.float32))
        if self._dimension is None and m.size:
            self._dimension = int(m.shape[1])
        return m
