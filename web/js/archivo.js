// Archivo: GET /api/documentos (paginado) y DELETE /api/documentos/{id} con confirmación en la página (sin
// window.confirm). Las miniaturas usan como `alt` el texto alternativo de su ficha (GET /api/fichas/{id}).
import { api, anunciar, el, ETIQUETA_ESTADO } from "./api.js";
import { mensaje, verFotoGuardada } from "./comun.js";

const POR_PAGINA = 24;
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
    el("p", { id: "confirmacion-texto", texto: `Se borrarán ${doc.documento_id}, sus vectores, su ficha y las entradas de caché que dependen de él. No se puede deshacer.` }),
    el("div", { clase: "fila" },
      el("button", { type: "button", clase: "boton peligro", onclick: () => { alCerrar = null; cerrarConfirmacion(); eliminar(doc); } }, "Sí, eliminar"),
      cancelar));
  cancelar.focus();
}

confirmacion.addEventListener("keydown", (ev) => { if (ev.key === "Escape") cerrarConfirmacion(); });

async function eliminar(doc) {
  try {
    const { cuerpo } = await api(`/documentos/${encodeURIComponent(doc.documento_id)}`, { method: "DELETE" });
    const texto = `Eliminado ${cuerpo.documento_id}: ${cuerpo.vectores_eliminados} vectores y ${cuerpo.entradas_cache_invalidadas} entradas de caché.`;
    await cargar();
    mensaje(estado, texto, "ok");
    anunciar(texto);
  } catch (e) { mensaje(estado, e.message); }
  selectorTipo.focus();   // la fila ya no existe: el foco vuelve a un punto estable de la página
}

/** Reemplaza el `alt` provisional de cada miniatura por el texto alternativo de su ficha. */
async function altDesdeFichas(filas) {
  await Promise.all(filas.map(async ({ doc, img }) => {
    try {
      const { cuerpo } = await api(`/fichas/${encodeURIComponent(doc.documento_id)}`, { aceptar: [404] });
      if (cuerpo?.ficha?.texto_alternativo) img.alt = cuerpo.ficha.texto_alternativo;
    } catch { /* se conserva el alt provisional */ }
  }));
}

async function cargar() {
  const tipo = selectorTipo.value;
  const params = new URLSearchParams({ pagina, por_pagina: POR_PAGINA });
  if (tipo) params.set("tipo", tipo);
  try {
    const { cuerpo } = await api(`/documentos?${params}`);
    const total = Math.max(1, Math.ceil(cuerpo.total / POR_PAGINA));
    document.getElementById("pagina").textContent = `Página ${pagina} de ${total} · ${cuerpo.total} documentos`;
    document.getElementById("anterior").disabled = pagina <= 1;
    document.getElementById("siguiente").disabled = pagina >= total;
    const conFicha = [];
    document.getElementById("filas").replaceChildren(...cuerpo.documentos.map((d) => {
      let vista = "—";
      if (d.tipo === "foto") {
        const img = el("img", { src: `/api/fotos/${encodeURIComponent(d.documento_id)}/miniatura?lado=96`, alt: `Foto ${d.nombre}`, width: "64" });
        if (d.estado_ficha) conFicha.push({ doc: d, img });
        // Clic en la miniatura: la foto en grande con lo que el archivo guardó de ella (su ficha)
        vista = el("button", { type: "button", clase: "boton-imagen miniatura-archivo", "aria-label": `Ver en grande ${d.nombre}`,
          onclick: () => verFotoGuardada(d.documento_id, { titulo: d.nombre, extra: [["Fecha de carga", (d.fecha || "").slice(0, 10)]] }) }, img);
      }
      const boton = el("button", { type: "button", clase: "boton secundario", "aria-label": `Eliminar ${d.nombre}`,
        onclick: (ev) => pedirConfirmacion(d, ev.currentTarget) }, "Eliminar");
      return el("tr", { "data-documento": d.documento_id },
        el("td", {}, vista),
        el("th", { scope: "row" }, d.tipo === "foto" ? el("a", { href: `catalogar.html?doc=${encodeURIComponent(d.documento_id)}`, texto: d.nombre }) : d.nombre,
          el("span", { clase: "id", texto: ` ${d.documento_id}` })),
        el("td", { texto: d.tipo === "foto" ? "Foto" : "Norma" }),
        el("td", { texto: d.estado_ficha ? (ETIQUETA_ESTADO[d.estado_ficha] || d.estado_ficha) : d.tipo === "foto" ? "Sin ficha" : "—" }),
        el("td", { texto: (d.fecha || "").slice(0, 10) }),
        el("td", {}, boton));
    }));
    if (!cuerpo.documentos.length) mensaje(estado, "No hay documentos con ese filtro.", "ok");
    altDesdeFichas(conFicha);
  } catch (e) { mensaje(estado, e.message); }
}

document.getElementById("filtros").addEventListener("submit", (ev) => { ev.preventDefault(); pagina = 1; cargar(); });
selectorTipo.addEventListener("change", () => { pagina = 1; cargar(); });
document.getElementById("anterior").addEventListener("click", () => { pagina = Math.max(1, pagina - 1); cargar(); });
document.getElementById("siguiente").addEventListener("click", () => { pagina += 1; cargar(); });
cargar();
