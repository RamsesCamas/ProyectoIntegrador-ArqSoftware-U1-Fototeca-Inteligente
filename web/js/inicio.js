// Página de inicio: estado del sistema (GET /api/health) y el archivo en cifras (GET /api/metricas).
// Los nombres de los componentes vienen de la API: la web no conoce los recursos internos (R8).
// Carga: /health cada 30 s (cada 10 s solo mientras los modelos se precalientan o algo falla) y /metricas una vez;
// nada se pide con la pestaña oculta, y al volver se refresca /health si ya pasó su intervalo.
import { api, anunciar, el, insignia } from "./api.js";
import { cuandoVisible, numero, porcentaje } from "./comun.js";

const INTERVALO_S = 30;
const INTERVALO_ARRANQUE_S = 10;

/** «hace 45 s», «hace 12 min», «hace 3 h 5 min». */
function hace(segundos) {
  const s = Math.max(0, Math.round(segundos));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  const m = Math.floor((s % 3600) / 60);
  return `${Math.floor(s / 3600)} h${m ? ` ${m} min` : ""}`;
}

function detalle(c) {
  if (c.estado === "error") return c.error || "No disponible";
  if (c.modelos_requeridos) {
    return `${numero(c.modelos_requeridos.length)} modelos descargados · ${numero((c.modelos_cargados || []).length)} cargados en memoria`;
  }
  if (c.colecciones) {
    const cols = Object.values(c.colecciones);
    if (!cols.length) return "Sin colecciones todavía";
    const total = cols.reduce((s, n) => s + (n ?? 0), 0);
    return `${numero(cols.length)} colecciones · ${numero(total)} vectores`;
  }
  if (c.filas) return Object.entries(c.filas).map(([t, n]) => `${t}: ${numero(n)}`).join(" · ");
  if (c.segundos_activo !== undefined) return `Activo desde hace ${hace(c.segundos_activo)}`;
  return "";
}

/** Detalle completo de las colecciones (nombre: puntos), como texto de ayuda de la tarjeta. */
function detalleLargo(c) {
  return c.colecciones ? Object.entries(c.colecciones).map(([n, p]) => `${n}: ${numero(p ?? 0)}`).join(" · ") : null;
}

let anterior = null;
let ultimaSalud = 0;
let temporizador = null;
let intervalo = INTERVALO_S;

async function actualizarSalud() {
  const contenedor = document.getElementById("componentes");
  const general = document.getElementById("estado-general");
  ultimaSalud = Date.now();
  try {
    const { cuerpo } = await api("/health", { aceptar: [503] });
    contenedor.replaceChildren(...Object.values(cuerpo.componentes).map((c) =>
      el("article", { clase: "tarjeta componente", title: detalleLargo(c) },
        el("h3", { texto: c.nombre }), insignia(c.estado), el("p", { texto: c.descripcion }),
        el("p", { clase: "detalle", texto: detalle(c) }))));
    general.replaceChildren(el("span", { texto: "Estado general: " }), insignia(cuerpo.estado),
      el("span", { clase: "sep", "aria-hidden": "true", texto: "·" }),
      el("span", { clase: "suave", texto: `versión de configuración ${cuerpo.versiones.configuracion}` }));
    const pre = cuerpo.precalentamiento || {};
    document.getElementById("precalentamiento").textContent =
      pre.estado === "en_curso" ? "Cargando los modelos en memoria…" :
      pre.estado === "listo" ? `Modelos listos en memoria (${pre.segundos} s).` :
      pre.estado === "error" ? "No se pudo cargar algún modelo." : "";
    if (anterior !== cuerpo.estado) anunciar(`Estado del sistema: ${cuerpo.estado}`);
    anterior = cuerpo.estado;
    intervalo = cuerpo.estado === "ok" && pre.estado !== "en_curso" ? INTERVALO_S : INTERVALO_ARRANQUE_S;
  } catch (e) {
    general.replaceChildren(insignia("error"), el("span", { texto: ` ${e.message}` }));
    if (anterior !== "sin_conexion") anunciar(e.message);
    anterior = "sin_conexion";
    intervalo = INTERVALO_ARRANQUE_S;
  }
}

function programar() {
  clearTimeout(temporizador);
  temporizador = null;
  if (document.hidden) return;
  temporizador = setTimeout(async () => { await actualizarSalud(); programar(); }, intervalo * 1000);
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) { clearTimeout(temporizador); temporizador = null; return; }
  if (!ultimaSalud) return;   // la primera carga la hace cuandoVisible()
  if (Date.now() - ultimaSalud >= intervalo * 1000) actualizarSalud().then(programar);
  else programar();
});

function cifra(valor, texto) {
  return el("article", { clase: "tarjeta" }, el("p", { clase: "cifra", texto: valor }), el("p", { clase: "cifra-etiqueta", texto }));
}

async function actualizarArchivo() {
  const contenedor = document.getElementById("cifras");
  try {
    const { cuerpo: m } = await api("/metricas");
    const a = m.accesibilidad || {};
    contenedor.replaceChildren(
      cifra(numero(a.fotos ?? 0), "fotos en el archivo"),
      cifra(numero(a.fichas_validadas ?? 0), "fichas validadas por el archivista"),
      cifra(porcentaje(a.porcentaje_alt_validado), "de las fotos tienen texto alternativo validado"),
      cifra(numero(a.requiere_revision ?? 0), "fichas requieren revisión"));
  } catch (e) {
    contenedor.replaceChildren(el("p", { clase: "mensaje error", role: "alert", texto: e.message }));
  }
}

cuandoVisible(() => { actualizarSalud().then(programar); actualizarArchivo(); });
