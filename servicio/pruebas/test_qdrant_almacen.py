"""C7 · Adaptador de Qdrant: el cliente HTTP pide respuestas sin comprimir.

Con gzip (lo que httpx pide por defecto), en conexiones keep-alive muchas respuestas pequeñas de Qdrant llegaban
tarde, y GET /health hace siete. La prueba no usa red: solo arma las peticiones, no las envía.
"""
from __future__ import annotations

from fototeca.datos.qdrant_almacen import QdrantAlmacen


def test_cliente_de_qdrant_pide_identity():
    almacen = QdrantAlmacen("http://qdrant-falso:6333")
    peticiones = [almacen._http.build_request("GET", "/collections/tesauro"),
                  almacen._http.build_request("POST", "/collections/tesauro/points/query",
                                              json={"query": [0.1, 0.2], "limit": 12, "with_payload": True})]
    for peticion in peticiones:
        assert peticion.headers["accept-encoding"] == "identity", peticion.url
