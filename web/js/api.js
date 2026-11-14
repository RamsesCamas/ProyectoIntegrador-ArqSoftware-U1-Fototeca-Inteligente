// Cliente de la API. La web SOLO habla con /api/* (nginx lo reenvía al servicio). Nunca con los modelos.
import { icono } from "./iconos.js";

export class ErrorApi extends Error {
  constructor(mensaje, { estado, cuerpo, traza } = {}) {
    super(mensaje);
    this.estado = estado;
    this.cuerpo = cuerpo;
    this.traza = traza;
  }
}

// Respuestas sin cuerpo JSON (p. ej. el proxy no alcanzó al servicio)
const SIN_CUERPO = {
  502: "El servicio no está disponible todavía. Espera unos segundos y vuelve a intentarlo.",
  503: "El servicio no está disponible todavía. Espera unos segundos y vuelve a intentarlo.",
  504: "El servicio tardó demasiado en responder. Vuelve a intentarlo en un momento.",
};

async function pedir(ruta, resto, headers) {
  let resp;
  try {
    resp = await fetch(`/api${ruta}`, { ...resto, headers: { Accept: "application/json", ...headers } });
  } catch (e) {
    throw new ErrorApi("No se pudo conectar con el servicio. ¿Está levantado con docker compose?", { estado: 0 });
  }
  const traza = resp.headers.get("X-Traza-Id");
  const tipo = resp.headers.get("Content-Type") || "";
  const cuerpo = tipo.includes("application/json") ? await resp.json() : null;
  return { ok: resp.ok, estado: resp.status, cuerpo, traza };
}

// GET idénticos y simultáneos comparten UNA petición (mientras está en curso; no es una caché): el shell y la página
// pueden pedir lo mismo a la vez sin duplicar la carga del servicio. Además lo protege: dos GET /health simultáneos
// hacen que uno responda 503 (el almacén se reporta en error). Quien la comparte recibe el mismo `cuerpo`: no mutarlo.
const enCurso = new Map();

export async function api(ruta, opciones = {}) {
  const { aceptar = [], headers = {}, ...resto } = opciones;
  const compartible = (!resto.method || resto.method === "GET") && !resto.body && !resto.signal && !Object.keys(headers).length;
  let promesa = compartible ? enCurso.get(ruta) : null;
  if (!promesa) {
    promesa = pedir(ruta, resto, headers);
    if (compartible) {
      enCurso.set(ruta, promesa);
      promesa.then(() => enCurso.delete(ruta), () => enCurso.delete(ruta));
    }
  }
  const r = await promesa;
  if (!r.ok && !aceptar.includes(r.estado)) {
    const mensaje = r.cuerpo?.error?.mensaje_seguro || r.cuerpo?.error?.mensaje || SIN_CUERPO[r.estado] || `Error ${r.estado}`;
    throw new ErrorApi(mensaje, { estado: r.estado, cuerpo: r.cuerpo, traza: r.traza });
  }
  return { cuerpo: r.cuerpo, traza: r.traza, estado: r.estado };
}

export function anunciar(texto) {
  const region = document.getElementById("anuncios");
  if (region) { region.textContent = ""; setTimeout(() => { region.textContent = texto; }, 50); }
}

export function el(etiqueta, atributos = {}, ...hijos) {
  const nodo = document.createElement(etiqueta);
  for (const [k, v] of Object.entries(atributos)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "clase") nodo.className = v;
    else if (k === "texto") nodo.textContent = v;
    else if (k.startsWith("on")) nodo.addEventListener(k.slice(2), v);
    else nodo.setAttribute(k, v === true ? "" : v);
  }
  for (const h of hijos.flat()) if (h !== null && h !== undefined) nodo.append(h instanceof Node ? h : document.createTextNode(String(h)));
  return nodo;
}

export const ETIQUETA_ESTADO = {
  ok: "En verde", degradado: "Degradado", error: "Con fallas", listo: "Listo", en_curso: "En curso", pendiente: "Pendiente",
  borrador: "Borrador", validada: "Validada", requiere_revision: "Requiere revisión", sin_conexion: "Sin conexión",
};

// Variante visual (clase de .insignia en base.css) e icono de cada estado: el texto siempre dice el estado, el color
// y el icono lo refuerzan. Un borrador es normal (neutra); «requiere revisión» y «degradado» son avisos.
const VARIANTE_ESTADO = {
  ok: ["ok", "check"], listo: ["ok", "check"], validada: ["ok", "check"],
  degradado: ["aviso", "alerta"], requiere_revision: ["aviso", "alerta"],
  error: ["error", "error"], sin_conexion: ["error", "error"],
  en_curso: ["info", "reloj"], pendiente: ["info", "reloj"], borrador: ["neutra", "pluma"],
};

export function insignia(estado) {
  const [clase, nombreIcono] = VARIANTE_ESTADO[estado] || ["neutra", "info"];
  return el("span", { clase: `insignia ${clase}` }, icono(nombreIcono), ETIQUETA_ESTADO[estado] || estado);
}
