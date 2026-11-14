"""Adaptador de Qdrant para el puerto `AlmacenVectorial` (C7), vía su API REST con httpx.

- Qdrant solo acepta ids enteros o UUID: los ids externos («xm-…#descripcion», «iptc-2025.1#alt-text») se
  convierten en UUID5 deterministas y el id original viaja en la carga útil (`id_externo`).
- Filtros con un formato propio y pequeño, independiente de Qdrant (las capas superiores no conocen Qdrant):
      {"validada": True}                     → must match
      {"documento_id": {"no": "xm-123"}}     → must_not match
      {"particion": {"en": ["archivo", …]}}  → match any
- Similitud coseno. Los vectores llegan normalizados L2 desde el embebedor.
"""
from __future__ import annotations

import uuid

import httpx
import numpy as np

from fototeca.dominio.entidades import ResultadoVectorial
from fototeca.dominio.errores import ServicioNoDisponible

_ESPACIO = uuid.UUID("6f1b6b0e-3a52-4c1e-9d1a-f0705ca7e7a1")
CAMPOS_INDEXADOS = ("documento_id", "validada", "particion", "campo", "fuente", "tipo", "clase")


def uuid_de(id_externo: str) -> str:
    return str(uuid.uuid5(_ESPACIO, id_externo))


def _filtro_qdrant(filtro: dict | None) -> dict | None:
    if not filtro:
        return None
    must, must_not = [], []
    for clave, valor in filtro.items():
        if isinstance(valor, dict) and "no" in valor:
            must_not.append({"key": clave, "match": {"value": valor["no"]}})
        elif isinstance(valor, dict) and "en" in valor:
            must.append({"key": clave, "match": {"any": list(valor["en"])}})
        else:
            must.append({"key": clave, "match": {"value": valor}})
    salida: dict = {}
    if must:
        salida["must"] = must
    if must_not:
        salida["must_not"] = must_not
    return salida


class QdrantAlmacen:
    def __init__(self, url: str, tiempo_limite_s: float = 60.0):
        self.url = url.rstrip("/")
        # Sin compresión: httpx pide gzip por defecto, Qdrant comprime hasta las respuestas de 1 KB y, en conexiones
        # keep-alive, muchas llegaban ~40 ms tarde: cada GET /collections/{n} de /health (menos de 1 ms con
        # `identity`) y algunas búsquedas. Ollama no comprime sus respuestas: su cliente no necesita este ajuste.
        self._http = httpx.Client(base_url=self.url, timeout=httpx.Timeout(5.0, read=tiempo_limite_s),
                                  headers={"Accept-Encoding": "identity"})
        self._dimensiones: dict[str, int] = {}

    def _pedir(self, metodo: str, ruta: str, **kw) -> dict:
        try:
            r = self._http.request(metodo, ruta, **kw)
        except httpx.HTTPError as e:
            raise ServicioNoDisponible(f"La base vectorial no responde: {type(e).__name__}") from e
        if r.status_code >= 400:
            raise ServicioNoDisponible(f"Error de la base vectorial ({r.status_code}): {r.text[:200]}")
        return r.json()

    def estado(self) -> dict:
        try:
            nombres = [c["name"] for c in self._http.get("/collections").json()["result"]["collections"]]
            puntos = {n: self._http.get(f"/collections/{n}").json()["result"].get("points_count") for n in sorted(nombres)}
            version = self._http.get("/").json().get("version")
        except Exception as e:  # noqa: BLE001
            return {"estado": "error", "error": f"Base vectorial no responde: {type(e).__name__}"}
        return {"estado": "ok", "version": version, "colecciones": puntos}

    def existe(self, nombre: str) -> bool:
        try:
            return self._http.get(f"/collections/{nombre}").status_code == 200
        except httpx.HTTPError as e:
            raise ServicioNoDisponible("La base vectorial no responde") from e

    def asegurar_coleccion(self, nombre: str, dimension: int) -> None:
        if self.existe(nombre):
            info = self._pedir("GET", f"/collections/{nombre}")["result"]
            actual = info["config"]["params"]["vectors"]["size"]
            if actual != dimension:
                raise ServicioNoDisponible(f"La colección {nombre} tiene dimensión {actual} y se esperaba {dimension}")
        else:
            self._pedir("PUT", f"/collections/{nombre}",
                        json={"vectors": {"size": int(dimension), "distance": "Cosine"}})
            for campo in CAMPOS_INDEXADOS:
                tipo = "bool" if campo == "validada" else "keyword"
                self._pedir("PUT", f"/collections/{nombre}/index?wait=true",
                            json={"field_name": campo, "field_schema": tipo})
        self._dimensiones[nombre] = int(dimension)

    def recrear_coleccion(self, nombre: str, dimension: int) -> None:
        if self.existe(nombre):
            self._pedir("DELETE", f"/collections/{nombre}")
        self.asegurar_coleccion(nombre, dimension)

    def insertar(self, coleccion: str, ids: list[str], vectores: np.ndarray, cargas: list[dict]) -> None:
        vectores = np.asarray(vectores, dtype=np.float32)
        for i in range(0, len(ids), 256):
            puntos = [{"id": uuid_de(e), "vector": v.tolist(), "payload": {**c, "id_externo": e}}
                      for e, v, c in zip(ids[i:i + 256], vectores[i:i + 256], cargas[i:i + 256])]
            self._pedir("PUT", f"/collections/{coleccion}/points?wait=true", json={"points": puntos})

    def buscar(self, coleccion: str, vector: np.ndarray, k: int,
               filtro: dict | None = None) -> list[ResultadoVectorial]:
        cuerpo = {"query": np.asarray(vector, dtype=np.float32).ravel().tolist(), "limit": int(k),
                  "with_payload": True}
        f = _filtro_qdrant(filtro)
        if f:
            cuerpo["filter"] = f
        datos = self._pedir("POST", f"/collections/{coleccion}/points/query", json=cuerpo)["result"]
        puntos = datos.get("points", datos) if isinstance(datos, dict) else datos
        return [ResultadoVectorial(id=p["payload"].get("id_externo", str(p["id"])), puntaje=float(p["score"]),
                                   carga=p["payload"]) for p in puntos]

    def obtener_vectores(self, coleccion: str, ids: list[str]) -> dict[str, np.ndarray]:
        if not ids:
            return {}
        datos = self._pedir("POST", f"/collections/{coleccion}/points",
                            json={"ids": [uuid_de(i) for i in ids], "with_vector": True, "with_payload": True})
        return {p["payload"]["id_externo"]: np.asarray(p["vector"], dtype=np.float32) for p in datos["result"]}

    def vectores_por_filtro(self, coleccion: str, filtro: dict | None = None) -> list[tuple[str, np.ndarray, dict]]:
        """Recorre la colección (scroll) y devuelve (id externo, vector, carga) de los puntos que cumplen el filtro."""
        if not self.existe(coleccion):
            return []
        salida, siguiente = [], None
        while True:
            cuerpo: dict = {"limit": 512, "with_vector": True, "with_payload": True}
            f = _filtro_qdrant(filtro)
            if f:
                cuerpo["filter"] = f
            if siguiente is not None:
                cuerpo["offset"] = siguiente
            datos = self._pedir("POST", f"/collections/{coleccion}/points/scroll", json=cuerpo)["result"]
            salida += [(p["payload"].get("id_externo", str(p["id"])), np.asarray(p["vector"], dtype=np.float32),
                        p["payload"]) for p in datos["points"]]
            siguiente = datos.get("next_page_offset")
            if siguiente is None:
                return salida

    def eliminar(self, coleccion: str, ids: list[str]) -> None:
        if ids and self.existe(coleccion):
            self._pedir("POST", f"/collections/{coleccion}/points/delete?wait=true",
                        json={"points": [uuid_de(i) for i in ids]})

    def eliminar_por_documento(self, coleccion: str, documento_id: str) -> None:
        if self.existe(coleccion):
            self._pedir("POST", f"/collections/{coleccion}/points/delete?wait=true",
                        json={"filter": _filtro_qdrant({"documento_id": documento_id})})

    def contar(self, coleccion: str, filtro: dict | None = None) -> int:
        if not self.existe(coleccion):
            return 0
        cuerpo: dict = {"exact": True}
        f = _filtro_qdrant(filtro)
        if f:
            cuerpo["filter"] = f
        return int(self._pedir("POST", f"/collections/{coleccion}/points/count", json=cuerpo)["result"]["count"])
