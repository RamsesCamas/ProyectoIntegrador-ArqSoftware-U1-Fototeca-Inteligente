// Cliente de la API. La web SOLO habla con /api/* (nginx lo reenvía al servicio). Nunca con los modelos.

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

export async function api(ruta, opciones = {}) {
  const { aceptar = [], headers = {}, ...resto } = opciones;
  let resp;
  try {
    resp = await fetch(`/api${ruta}`, { ...resto, headers: { Accept: "application/json", ...headers } });
  } catch (e) {
    throw new ErrorApi("No se pudo conectar con el servicio. ¿Está levantado con docker compose?", { estado: 0 });
  }
  const traza = resp.headers.get("X-Traza-Id");
  const tipo = resp.headers.get("Content-Type") || "";
  const cuerpo = tipo.includes("application/json") ? await resp.json() : null;
  if (!resp.ok && !aceptar.includes(resp.status)) {
    const mensaje = cuerpo?.error?.mensaje_seguro || cuerpo?.error?.mensaje || SIN_CUERPO[resp.status] || `Error ${resp.status}`;
    throw new ErrorApi(mensaje, { estado: resp.status, cuerpo, traza });
  }
  return { cuerpo, traza, estado: resp.status };
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
  borrador: "Borrador", validada: "Validada", requiere_revision: "Requiere revisión",
};

export function insignia(estado) {
  const clase = ["ok", "listo", "validada"].includes(estado) ? "ok" : estado === "error" ? "error" : "degradado";
  return el("span", { clase: `insignia ${clase}`, texto: ETIQUETA_ESTADO[estado] || estado });
}
