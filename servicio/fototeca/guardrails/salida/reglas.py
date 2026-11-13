"""Verificaciones de salida que no necesitan modelos: esquema, reglas IPTC, léxico de atributos sensibles y fuentes.

- `esquema`: la ficha valida contra el esquema Pydantic → si no, reintentar (lo aplica el gateway/C2).
- `reglas_iptc`: texto alternativo no vacío y ≤250 caracteres, sin empezar con «imagen de», «foto de» ni
  «fotografía de»; titular ≤120. Se recorta por oración y se normaliza el inicio; si queda vacío → reintentar.
- `atributos_sensibles` (etapa léxica): etnia, raza, religión, orientación, discapacidad, salud y nombres
  propios de personas. Si el léxico detecta algo, C2 consulta P6 (Qwen) y aplica la política.
- `fuentes`: cada campo tiene al menos una fuente y todos los ids existen en el contexto entregado al modelo.
"""
from __future__ import annotations

import re

from pydantic import ValidationError

from fototeca.dominio.esquemas_ficha import Ficha
from fototeca.guardrails.politicas import politica
from fototeca.guardrails.resultado import ResultadoGuardrail

INICIOS_PROHIBIDOS = re.compile(r"^\s*(una?\s+)?(imagen|foto|fotografía|fotografia|image|photo)\s+(de|del|que muestra|en la que|donde)\s+", re.I)

LEXICO_SENSIBLE = {
    "etnia_raza": r"\b(ind[ií]gena|afro\w*|negr[oa]s?|blanc[oa]s? de piel|asi[aá]tic[oa]s?|latin[oa]s?|caucás\w+|mestiz[oa]s?|"
                  r"gitan[oa]s?|étnic[oa]s?|etnia|raza|raciales?|árabes?|judí[oa]s?)\b",
    "religion": r"\b(musulman[ae]s?|islámic[oa]s?|cristian[oa]s?|católic[oa]s?|evangélic[oa]s?|budistas?|hindú(es)?|"
                r"religios[oa]s? (de|del)|ateo|atea)\b",
    "orientacion": r"\b(gay|gays|lesbianas?|homosexual(es)?|heterosexual(es)?|bisexual(es)?|trans(género|sexual)?|queer)\b",
    "discapacidad": r"\b(discapacitad[oa]s?|minusválid[oa]s?|invident[ea]s?|cieg[oa]s?|sord[oa]s?|parapléjic[oa]s?|"
                    r"en silla de ruedas|con discapacidad|autista|síndrome de down)\b",
    "salud": r"\b(enferm[oa]s?|enfermedad|cáncer|diabétic[oa]s?|embarazada|obes[oa]s?|depresión|deprimid[oa]s?|"
             r"vih|sida|covid)\b",
}
_LEXICO = {k: re.compile(v, re.I) for k, v in LEXICO_SENSIBLE.items()}
# Nombres propios de personas: «Nombre Apellido» precedido de un verbo o rol típico de identificación.
_NOMBRE_PROPIO = re.compile(r"\b(el|la|los|las)?\s*(señor|señora|presidente|presidenta|alcalde|alcaldesa|doctor|doctora|"
                            r"maestro|maestra|profesor|profesora)\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)?")

CAMPOS_TEXTO = ("titular", "descripcion", "texto_alternativo", "descripcion_extendida")
# Límites de longitud del esquema de la ficha (titular 120 y texto alternativo 250 son los de IPTC/06).
LIMITES = {c: Ficha.model_fields[c].metadata[0].max_length for c in CAMPOS_TEXTO}
NOMBRE_CAMBIO = {"titular": "titular_recortado", "texto_alternativo": "alt_recortado",
                 "descripcion": "descripcion_recortada", "descripcion_extendida": "descripcion_extendida_recortada"}


def recortar_longitudes(datos: dict) -> tuple[dict, list[str]]:
    """Recorta por oración los campos de texto que exceden su límite ANTES de validar el esquema: la política de
    `reglas_iptc` ante un texto largo es recortar, no reintentar (ADR-05). Devuelve los datos y los cambios hechos."""
    salida, cambios = dict(datos), []
    for campo, maximo in LIMITES.items():
        valor = salida.get(campo)
        if isinstance(valor, str) and len(valor.strip()) > maximo:
            salida[campo] = _recortar_por_oracion(valor.strip(), maximo)
            cambios.append(NOMBRE_CAMBIO[campo])
    return salida, cambios


# Alias de citas del prompt (F1, R2, T3). El archivista no los ve, así que una advertencia que los menciona no le sirve.
_ALIAS_CITA = re.compile(r"\b[FRT]\d{1,2}\b")


def limpiar_advertencias(advertencias) -> list[str]:
    """Quita de las advertencias del modelo lo que no es texto o habla de los alias internos del prompt (en R3, LFM3
    copió `F1`…`F5` como advertencias en 8 de 30 fichas)."""
    if not isinstance(advertencias, list):
        return []
    return [a.strip() for a in advertencias if isinstance(a, str) and a.strip() and not _ALIAS_CITA.search(a)]


def verificar_esquema(datos: dict) -> tuple[Ficha | None, ResultadoGuardrail]:
    try:
        ficha = Ficha.model_validate(datos)
        return ficha, ResultadoGuardrail("esquema", "aprobada")
    except ValidationError as e:
        errores = [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()][:5]
        return None, ResultadoGuardrail("esquema", "marcada", politica_aplicada=politica("esquema"),
                                        detalle={"errores": errores})


def _recortar_por_oracion(texto: str, maximo: int) -> str:
    if len(texto) <= maximo:
        return texto
    oraciones = re.split(r"(?<=[.!?;])\s+", texto)
    salida = ""
    for o in oraciones:
        if len(salida) + len(o) + (1 if salida else 0) > maximo:
            break
        salida = f"{salida} {o}".strip()
    if not salida:  # una sola oración larguísima: corte por palabra
        corte = texto.rfind(" ", 0, maximo - 1)
        salida = texto[:corte if corte > maximo // 2 else maximo - 1].rstrip(" ,;:")
    return salida


def _normalizar_inicio(texto: str) -> str:
    nuevo = INICIOS_PROHIBIDOS.sub("", texto).strip()
    return nuevo[:1].upper() + nuevo[1:] if nuevo else nuevo


def aplicar_reglas_iptc(ficha: Ficha, recortes_previos: list[str] | None = None) -> tuple[Ficha, ResultadoGuardrail]:
    """`recortes_previos`: los que hizo `recortar_longitudes` antes del esquema (se reportan aquí, en reglas_iptc)."""
    cambios = list(recortes_previos or [])
    alt, titular = ficha.texto_alternativo.strip(), ficha.titular.strip()
    if INICIOS_PROHIBIDOS.match(alt):
        alt = _normalizar_inicio(alt)
        cambios.append("inicio_normalizado")
    if len(alt) > 250:
        alt = _recortar_por_oracion(alt, 250)
        cambios.append("alt_recortado")
    if len(titular) > 120:
        titular = _recortar_por_oracion(titular, 120)
        cambios.append("titular_recortado")
    if not alt:
        return ficha, ResultadoGuardrail("reglas_iptc", "marcada", valor=0.0, umbral=250.0,
                                         politica_aplicada="reintentar", detalle={"motivo": "texto alternativo vacío"})
    nueva = ficha.model_copy(update={"texto_alternativo": alt, "titular": titular})
    if cambios:
        return nueva, ResultadoGuardrail("reglas_iptc", "sanitizado", valor=float(len(alt)), umbral=250.0,
                                         politica_aplicada=politica("reglas_iptc"), detalle={"cambios": cambios})
    return nueva, ResultadoGuardrail("reglas_iptc", "aprobada", valor=float(len(alt)), umbral=250.0)


def detectar_sensibles(ficha: Ficha) -> dict[str, list[str]]:
    """Etapa léxica: {campo: [fragmentos sospechosos]} (vacío si no hay nada)."""
    hallazgos: dict[str, list[str]] = {}
    for campo in CAMPOS_TEXTO:
        texto = getattr(ficha, campo) or ""
        frag = [m.group(0) for r in _LEXICO.values() for m in r.finditer(texto)]
        frag += [m.group(0).strip() for m in _NOMBRE_PROPIO.finditer(texto)]
        if frag:
            hallazgos[campo] = sorted(set(frag))
    return hallazgos


def eliminar_frases(ficha: Ficha, hallazgos: dict[str, list[str]]) -> Ficha:
    """Quita las oraciones que contienen los fragmentos sensibles confirmados."""
    cambios = {}
    for campo, fragmentos in hallazgos.items():
        oraciones = re.split(r"(?<=[.!?;])\s+", getattr(ficha, campo) or "")
        limpias = [o for o in oraciones if not any(f.lower() in o.lower() for f in fragmentos)]
        cambios[campo] = " ".join(limpias).strip()
    return ficha.model_copy(update=cambios)


def verificar_fuentes(fuentes: dict[str, list[str]], ids_validos: set[str],
                      campos: tuple[str, ...] = ("titular", "descripcion", "texto_alternativo", "palabras_clave"),
                      campos_presentes: set[str] | None = None) -> tuple[dict[str, list[str]], ResultadoGuardrail]:
    """Quita las fuentes inválidas (ids que no estaban en el contexto). Si un campo queda sin fuentes → marcar.

    Un id citado sin su prefijo (`xm-…` en lugar de `foto:xm-…`) se acepta solo si corresponde a exactamente un id
    válido: es el mismo id del contexto mal copiado, no uno inventado."""
    sin_prefijo: dict[str, list[str]] = {}
    for v in ids_validos:
        if ":" in v:
            sin_prefijo.setdefault(v.split(":", 1)[1], []).append(v)

    def normalizar(i):
        if not isinstance(i, str) or i in ids_validos:
            return i
        candidatos = sin_prefijo.get(i.strip(), [])
        return candidatos[0] if len(candidatos) == 1 else i

    limpias: dict[str, list[str]] = {}
    invalidas = []
    for campo, ids in (fuentes or {}).items():
        if not isinstance(ids, list):
            continue
        ids = [normalizar(i) for i in ids]
        buenas = [i for i in ids if isinstance(i, str) and i in ids_validos]
        invalidas += [i for i in ids if i not in buenas]
        if buenas:
            limpias[campo] = list(dict.fromkeys(buenas))
    revisar = [c for c in campos if (campos_presentes is None or c in campos_presentes) and c not in limpias]
    detalle = {"invalidas_quitadas": len(invalidas), "campos_sin_fuente": revisar}
    if revisar:
        return limpias, ResultadoGuardrail("fuentes", "marcada", valor=float(len(invalidas)),
                                           politica_aplicada=politica("fuentes"), detalle=detalle)
    if invalidas:
        return limpias, ResultadoGuardrail("fuentes", "sanitizado", valor=float(len(invalidas)),
                                           politica_aplicada=politica("fuentes"), detalle=detalle)
    return limpias, ResultadoGuardrail("fuentes", "aprobada", valor=0.0)
