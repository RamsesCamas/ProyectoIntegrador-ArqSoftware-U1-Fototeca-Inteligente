// Página de inicio: estado del sistema (GET /api/health) y el archivo en cifras (GET /api/metricas).
// Los nombres de los componentes vienen de la API: la web no conoce los recursos internos (R8).
import { api, anunciar, el, insignia } from "./api.js";
import { porcentaje } from "./comun.js";

function detalle(c) {
  if (c.estado === "error") return c.error || "No disponible";
  if (c.modelos_requeridos) {
    return `${c.modelos_requeridos.length} modelos descargados · ${(c.modelos_cargados || []).length} cargados en memoria`;
  }
  if (c.colecciones) {
    const cols = Object.entries(c.colecciones);
    return cols.length ? cols.map(([n, p]) => `${n}: ${p ?? 0}`).join(" · ") : "Sin colecciones todavía";
  }
  if (c.filas) return Object.entries(c.filas).map(([t, n]) => `${t}: ${n}`).join(" · ");
  if (c.segundos_activo !== undefined) return `Activo desde hace ${c.segundos_activo} s`;
  return "";
}

let anterior = null;

async function actualizarSalud() {
  const contenedor = document.getElementById("componentes");
  const general = document.getElementById("estado-general");
  try {
    const { cuerpo } = await api("/health", { aceptar: [503] });
    contenedor.replaceChildren(...Object.values(cuerpo.componentes).map((c) =>
      el("article", { clase: "tarjeta" },
        el("h3", { texto: c.nombre }), insignia(c.estado), el("p", { texto: c.descripcion }), el("p", { texto: detalle(c) }))));
    general.replaceChildren(el("span", { texto: "Estado general: " }), insignia(cuerpo.estado),
      el("span", { texto: ` · versión de configuración ${cuerpo.versiones.configuracion}` }));
    const pre = cuerpo.precalentamiento || {};
    document.getElementById("precalentamiento").textContent =
      pre.estado === "en_curso" ? "Cargando los modelos en memoria…" :
      pre.estado === "listo" ? `Modelos listos en memoria (${pre.segundos} s).` :
      pre.estado === "error" ? "No se pudo cargar algún modelo." : "";
    if (anterior !== cuerpo.estado) anunciar(`Estado del sistema: ${cuerpo.estado}`);
    anterior = cuerpo.estado;
  } catch (e) {
    general.replaceChildren(insignia("error"), el("span", { texto: ` ${e.message}` }));
    if (anterior !== "sin_conexion") anunciar(e.message);
    anterior = "sin_conexion";
  }
}

function cifra(valor, texto) {
  return el("article", { clase: "tarjeta" }, el("p", { clase: "cifra", texto: valor }), el("p", { texto }));
}

async function actualizarArchivo() {
  const contenedor = document.getElementById("cifras");
  try {
    const { cuerpo: m } = await api("/metricas");
    const a = m.accesibilidad || {};
    contenedor.replaceChildren(
      cifra(String(a.fotos ?? 0), "fotos en el archivo"),
      cifra(String(a.fichas_validadas ?? 0), "fichas validadas por el archivista"),
      cifra(porcentaje(a.porcentaje_alt_validado), "de las fotos tienen texto alternativo validado"),
      cifra(String(a.requiere_revision ?? 0), "fichas requieren revisión"));
  } catch (e) {
    contenedor.replaceChildren(el("p", { clase: "mensaje error", role: "alert", texto: e.message }));
  }
}

actualizarSalud();
actualizarArchivo();
setInterval(actualizarSalud, 10000);
setInterval(actualizarArchivo, 60000);
