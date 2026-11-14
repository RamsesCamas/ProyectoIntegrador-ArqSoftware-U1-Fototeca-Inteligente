// Archivo: GET /api/documentos (paginado) y DELETE /api/documentos/{id} con confirmación en la página (sin
// window.confirm). Cada documento trae `titular` y `texto_alternativo` de su ficha (null si no tiene): el `alt` de la
// miniatura y el titular salen de ahí, sin una petición por fila. Respaldo para una API anterior que no los traiga:
// solo entonces se pide GET /api/fichas/{id} por cada foto con ficha.
import { api, anunciar, el, insignia } from "./api.js";
import { mensaje, numero, verFotoGuardada } from "./comun.js";

const POR_PAGINA = 24;
const VISIBLES_SIN_DIFERIR = 8;   // filas que suelen verse sin desplazarse: sus miniaturas no se difieren
const parametros = new URLSearchParams(location.search);
let pagina = Math.max(1, Number(parametros.get("pagina")) || 1);
const estado = document.getElementById("estado");
const confirmacion = document.getElementById("confirmacion");
const selectorTipo = document.getElementById("tipo");
if (parametros.has("tipo")) selectorTipo.value = parametros.get("tipo");
let alCerrar = null;

function cerrarConfirmacion() {
  confirmacion.hidden = true;
  confirmacion.replaceChildren();
  if (alCerrar) { alCerrar.focus(); alCerrar = null; }
}

function pedirConfirmacion(doc, origen) {
  alCerrar = origen;
  confirmacion.hidden = false;
  const cancelar = el("button", { type: "button", clase: "boton secundario", onclick: cerrarConfirmacion }, "Cancelar");
  confirmacion.replaceChildren(
    el("h2", { id: "confirmacion-titulo", texto: `¿Eliminar «${doc.nombre}»?` }),
    el("p", { id: "confirmacion-texto", texto: `Se borrarán ${doc.documento_id}${doc.titular ? ` («${doc.titular}»)` : ""}, sus vectores, `
      + "su ficha y las entradas de caché que dependen de él. No se puede deshacer." }),
    el("div", { clase: "fila" },
      el("button", { type: "button", clase: "boton peligro", onclick: () => { alCerrar = null; cerrarConfirmacion(); eliminar(doc); } }, "Sí, eliminar"),
      cancelar));
  cancelar.focus();
}

confirmacion.addEventListener("keydown", (ev) => { if (ev.key === "Escape") cerrarConfirmacion(); });

async function eliminar(doc) {
  try {
    const { cuerpo } = await api(`/documentos/${encodeURIComponent(doc.documento_id)}`, { method: "DELETE" });
    const texto = `Eliminado ${cuerpo.documento_id}: ${numero(cuerpo.vectores_eliminados)} vectores y ${numero(cuerpo.entradas_cache_invalidadas)} entradas de caché.`;
    await cargar();
    mensaje(estado, texto, "ok");
    anunciar(texto);
  } catch (e) { mensaje(estado, e.message); }
  selectorTipo.focus();   // la fila ya no existe: el foco vuelve a un punto estable de la página
}

/** Respaldo (API sin `titular`/`texto_alternativo`): completa cada fila con su ficha (GET /api/fichas/{id}). */
async function completarDesdeFichas(filas) {
  await Promise.all(filas.map(async ({ doc, img, enlace, id }) => {
    try {
      const { cuerpo } = await api(`/fichas/${encodeURIComponent(doc.documento_id)}`, { aceptar: [404] });
      const ficha = cuerpo?.ficha;
      if (ficha?.texto_alternativo) img.alt = ficha.texto_alternativo;
      if (ficha?.titular) {
        doc.titular = ficha.titular;
        enlace.textContent = ficha.titular;
        id.textContent = `${doc.nombre} · ${doc.documento_id}`;
      }
    } catch { /* se conservan el alt y el nombre provisionales */ }
  }));
}

function fila(d, i, pendientes) {
  const traeCampos = "texto_alternativo" in d;   // API nueva: los campos vienen (aunque sean null)
  const titular = traeCampos ? d.titular : null;
  let vista = "—";
  let img = null;
  if (d.tipo === "foto") {
    img = el("img", { src: `/api/fotos/${encodeURIComponent(d.documento_id)}/miniatura?lado=96`,
      alt: (traeCampos && d.texto_alternativo) || `Foto ${d.nombre}`, width: "64", height: "48",
      loading: i >= VISIBLES_SIN_DIFERIR ? "lazy" : null, decoding: "async" });
    // Clic en la miniatura: la foto en grande con lo que el archivo guardó de ella (su ficha)
    vista = el("button", { type: "button", clase: "boton-imagen miniatura-archivo",
      onclick: () => verFotoGuardada(d.documento_id, { titulo: titular || d.nombre, extra: [["Fecha de carga", (d.fecha || "").slice(0, 10)]] }) },
      img, el("span", { clase: "solo-lectores", texto: " (ver en grande)" }));
  }
  const enlace = d.tipo === "foto"
    ? el("a", { href: `catalogar.html?doc=${encodeURIComponent(d.documento_id)}`, texto: titular || d.nombre })
    : el("span", { clase: "nombre", texto: d.nombre });
  const id = el("span", { clase: "id", texto: titular ? `${d.nombre} · ${d.documento_id}` : d.documento_id });
  if (d.tipo === "foto" && d.estado_ficha && !traeCampos) pendientes.push({ doc: d, img, enlace, id });
  const boton = el("button", { type: "button", clase: "boton discreto peligro", "aria-label": `Eliminar ${d.nombre}`,
    onclick: (ev) => pedirConfirmacion(d, ev.currentTarget) }, "Eliminar…");
  return el("tr", { "data-documento": d.documento_id },
    el("td", {}, vista),
    el("th", { scope: "row", clase: "celda-documento" }, enlace, id),
    el("td", { texto: d.tipo === "foto" ? "Foto" : "Norma" }),
    el("td", {}, d.estado_ficha ? insignia(d.estado_ficha) : el("span", { clase: "suave", texto: d.tipo === "foto" ? "Sin ficha" : "—" })),
    el("td", { texto: (d.fecha || "").slice(0, 10) }),
    el("td", {}, boton));
}

async function cargar() {
  const tipo = selectorTipo.value;
  const params = new URLSearchParams({ pagina, por_pagina: POR_PAGINA });
  if (tipo) params.set("tipo", tipo);
  try {
    const { cuerpo } = await api(`/documentos?${params}`);
    estado.replaceChildren();
    const total = Math.max(1, Math.ceil(cuerpo.total / POR_PAGINA));
    document.getElementById("pagina").textContent = `Página ${numero(pagina)} de ${numero(total)} · ${numero(cuerpo.total)} documentos`;
    document.getElementById("anterior").disabled = pagina <= 1;
    document.getElementById("siguiente").disabled = pagina >= total;
    const pendientes = [];
    document.getElementById("filas").replaceChildren(...cuerpo.documentos.map((d, i) => fila(d, i, pendientes)));
    if (!cuerpo.documentos.length) mensaje(estado, "No hay documentos con ese filtro.", "info");
    if (pendientes.length) completarDesdeFichas(pendientes);
  } catch (e) { mensaje(estado, e.message); }
}

document.getElementById("filtros").addEventListener("submit", (ev) => { ev.preventDefault(); pagina = 1; cargar(); });
selectorTipo.addEventListener("change", () => { pagina = 1; cargar(); });
document.getElementById("anterior").addEventListener("click", () => { pagina = Math.max(1, pagina - 1); cargar(); });
document.getElementById("siguiente").addEventListener("click", () => { pagina += 1; cargar(); });
cargar();
