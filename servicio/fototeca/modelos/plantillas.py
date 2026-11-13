"""Prompts versionados (informe, Tabla 11; ADR-11): `modelos/prompts/Pn_nombre.md` con encabezado YAML.

Formato de cada archivo: encabezado YAML (version, tarea, modelo_preferido, modelo_respaldo, num_predict,
temperatura, con_imagen) y las secciones «## Sistema», «## Usuario» y «## Esquema» (JSON en un bloque de código).
La versión de cada prompt forma parte de la versión de configuración: cambiar un prompt invalida la caché.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from fototeca.dominio.entidades import Mensaje

DIR_PROMPTS = Path(__file__).resolve().parent / "prompts"
_VARIABLE = re.compile(r"\{(\w+)\}")


def rellenar(texto: str, variables: dict) -> str:
    """Sustituye solo `{nombre}` con nombres conocidos: las llaves literales (p. ej. JSON de ejemplo) se respetan."""
    return _VARIABLE.sub(lambda m: str(variables[m.group(1)]) if m.group(1) in variables else m.group(0), texto)


@dataclass(frozen=True)
class Plantilla:
    tarea: str
    nombre: str
    version: int
    modelo_preferido: str          # rol: vision | composicion
    modelo_respaldo: str | None
    num_predict: int
    temperatura: float
    con_imagen: bool
    sistema: str
    usuario: str
    esquema: dict

    def mensajes(self, variables: dict) -> list[Mensaje]:
        return [Mensaje("system", rellenar(self.sistema, variables)), Mensaje("user", rellenar(self.usuario, variables))]


def leer_plantilla(ruta: Path) -> Plantilla:
    texto = ruta.read_text(encoding="utf-8")
    _, encabezado, cuerpo = texto.split("---", 2)
    meta = yaml.safe_load(encabezado)
    secciones = dict(re.findall(r"^## (\w+)\s*\n(.*?)(?=^## |\Z)", cuerpo, flags=re.M | re.S))
    esquema_txt = re.search(r"```json\s*(.*?)```", secciones["Esquema"], flags=re.S).group(1)
    return Plantilla(tarea=meta["tarea"], nombre=meta["nombre"], version=int(meta["version"]),
                     modelo_preferido=meta["modelo_preferido"], modelo_respaldo=meta.get("modelo_respaldo"),
                     num_predict=int(meta["num_predict"]), temperatura=float(meta["temperatura"]),
                     con_imagen=bool(meta.get("con_imagen", False)), sistema=secciones["Sistema"].strip(),
                     usuario=secciones["Usuario"].strip(), esquema=json.loads(esquema_txt))


def cargar_plantillas(directorio: Path = DIR_PROMPTS) -> dict[str, Plantilla]:
    return {p.tarea: p for p in (leer_plantilla(r) for r in sorted(directorio.glob("P*.md")))}


def versiones(plantillas: dict[str, Plantilla]) -> dict[str, str]:
    """`nombre@vN#huella`: la huella (sha256 del sistema, el usuario, el esquema y el encabezado que decide la generación:
    modelo preferido, respaldo, `num_predict` y temperatura) cambia con cualquier edición del prompt aunque nadie suba
    la versión, y así la caché de fichas se invalida (forma parte de la versión de configuración). El encabezado entra
    desde que P3 pasó de LFM3 a Qwen (ADR-01): antes, ese cambio no invalidaba la caché."""
    salida = {}
    for t, p in sorted(plantillas.items()):
        huella = hashlib.sha256(json.dumps([p.sistema, p.usuario, p.esquema, p.modelo_preferido, p.modelo_respaldo,
                                            p.num_predict, p.temperatura], ensure_ascii=False,
                                           sort_keys=True).encode("utf-8")).hexdigest()[:8]
        salida[t] = f"{p.nombre}@v{p.version}#{huella}"
    return salida


CAMPOS_CON_CITA = ("titular", "descripcion", "texto_alternativo")


def esquema_con_fuentes(esquema: dict, ids: list[str]) -> dict:
    """Copia del esquema para la gramática de la salida: cada campo de `fuentes` pasa a ser obligatorio y sus elementos
    solo pueden ser uno de `ids` (los que el modelo vio en el prompt). Sin ids, las listas quedan vacías. Con ids, los
    campos de texto (titular, descripción y texto alternativo) piden al menos una cita: con P3 v3, LFM3 dejaba sin cita el
    titular y la descripción en 7 de 10 fichas de `ajuste_prompts`, aunque su redacción sigue las reglas recuperadas.

    La validación de la respuesta sigue usando el esquema estático: una cita inválida que llegara a pasar la quita el
    guardrail `fuentes`, no la descarta el gateway."""
    nuevo = json.loads(json.dumps(esquema))
    fuentes = nuevo.get("properties", {}).get("fuentes")
    if not isinstance(fuentes, dict) or not isinstance(fuentes.get("properties"), dict):
        return nuevo
    ids = list(dict.fromkeys(i for i in ids if i))
    for campo, sub in fuentes["properties"].items():
        if ids:
            sub["items"] = {"type": "string", "enum": ids}
            if campo in CAMPOS_CON_CITA:
                sub["minItems"] = 1
        else:
            sub["maxItems"] = 0
    fuentes["required"] = list(fuentes["properties"])
    return nuevo
