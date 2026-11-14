// Archivo: GET /api/documentos (paginado, con filtro por tipo) y DELETE /api/documentos/{id} con confirmación en la
// página (sin window.confirm). El listado trae `titular` y `texto_alternativo` de cada ficha (null si no tiene): el
// titular y el `alt` de la miniatura salen de ahí, con una sola petición por página. Bajo 640 px de contenido cada fila
// se muestra como tarjeta (CSS); los roles ARIA explícitos conservan la semántica de tabla.
import { api, anunciar, el, insignia } from "./api.js";
import { mensaje, miniatura, numero, verFotoGuardada } from "./comun.js";
import { icono } from "./iconos.js";

const POR_PAGINA = 24;
const VISIBLES_SIN_DIFERIR = 8;   // filas que suelen verse sin desplazarse: sus miniaturas no se difieren
const COLUMNAS = 6;
const TIPOS = { foto: ["Foto", "foto"], norma: ["Norma", "regla"] };
const CONTEO = { foto: ["foto", "fotos"], norma: ["norma", "normas"], "": ["documento", "documentos"] };
const parametros = new URLSearchParams(location.search);
let pagina = Math.max(1, Number(parametros.get("pagina")) || 1);
const estado = document.getElementById("estado");
const confirmacion = document.getElementById("confirmacion");
const filas = document.getElementById("filas");
const tabla = filas.closest("table");
const paginaciones = [["pagina", "anterior", "siguiente"], ["pagina-abajo", "anterior-abajo", "siguiente-abajo"]]
  .map(([t, a, s]) => ({ texto: document.getElementById(t), anterior: document.getElementById(a), siguiente: document.getElementById(s) }));
const radios = [...document.querySelectorAll('#filtro-tipo input[name="tipo"]')];
if (parametros.has("tipo")) {
  const elegido = radios.find((r) => r.value === parametros.get("tipo"));
  if (elegido) elegido.checked = true;
}
const tipoActual = () => radios.find((r) => r.checked)?.value ?? "foto";
let alCerrar = null;
let turno = 0;

const dos = (n) => String(n).padStart(2, "0");
/** Fecha local en ISO de 24 h, «2026-11-13 14:00» (el mismo formato que Métricas, sin segundos). */
function fecha(iso) {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return "—";
  return `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())} ${dos(d.getHours())}:${dos(d.getMinutes())}`;
}

/** «nombre · id» solo si el nombre original dice algo más que el id (las fotos del archivo se llaman como su hash). */
function meta(d, principal) {
  const base = (d.nombre || "").replace(/\.[^.]+$/, "");
  const repetido = !d.nombre || d.nombre === principal || (base && d.documento_id.endsWith(base));
  return el("span", { clase: "documento-meta", title: d.documento_id }, repetido ? "" : `${d.nombre} · `, el("span", { clase: "id", texto: d.documento_id }));
}

/** Montura de 72 × 54: la miniatura de la foto o, para una norma, un marco con su icono. */
function montura(d, { alt, diferida = false } = {}) {
  if (d.tipo !== "foto") return el("span", { clase: "montura montura-norma", "aria-hidden": "true" }, icono("regla"));
  return el("span", { clase: "montura" }, miniatura(d.documento_id, { alt, lado: 96, ancho: 72, alto: 54, diferida }));
}

function cerrarConfirmacion() {
  confirmacion.hidden = true;
  confirmacion.replaceChildren();
  if (alCerrar) { alCerrar.focus(); alCerrar = null; }
}

function pedirConfirmacion(doc, origen) {
  alCerrar = origen;
  const cancelar = el("button", { type: "button", clase: "boton secundario", onclick: cerrarConfirmacion }, "Cancelar");
  const titulo = doc.titular || doc.nombre;
  confirmacion.replaceChildren(
    montura(doc, { alt: "" }),
    el("div", { clase: "confirmacion-cuerpo" },
      el("h2", { id: "confirmacion-titulo" }, icono("alerta"), "¿Eliminar este documento?"),
      el("p", { clase: "confirmacion-documento" }, el("strong", { texto: titulo }), meta(doc, titulo)),
      el("p", { id: "confirmacion-texto", texto: "Se borrarán el documento, sus vectores, su ficha y las entradas de caché que dependen de él. No se puede deshacer." }),
      el("div", { clase: "confirmacion-acciones" },
        el("button", { type: "button", clase: "boton peligro", onclick: () => { alCerrar = null; cerrarConfirmacion(); eliminar(doc); } },
          icono("papelera"), "Sí, eliminar"),
        cancelar)));
  confirmacion.hidden = false;
  cancelar.focus();
}

confirmacion.addEventListener("keydown", (ev) => { if (ev.key === "Escape") cerrarConfirmacion(); });

/** Punto estable para el foco cuando la fila que lo tenía desaparece: la opción elegida del filtro. */
const enfocarFiltro = () => radios.find((r) => r.checked)?.focus();

async function eliminar(doc) {
  mensaje(estado, `Eliminando ${doc.documento_id}…`, "info");
  try {
    const { cuerpo } = await api(`/documentos/${encodeURIComponent(doc.documento_id)}`, { method: "DELETE" });
    const texto = `Eliminado ${cuerpo.documento_id}: ${numero(cuerpo.vectores_eliminados)} vectores y ${numero(cuerpo.entradas_cache_invalidadas)} entradas de caché.`;
    await cargar();
    mensaje(estado, texto, "ok");
    anunciar(texto);
  } catch (e) { mensaje(estado, e.message); }
  enfocarFiltro();
}

function estadoFicha(d) {
  if (d.tipo !== "foto") return el("span", { clase: "suave", texto: "No aplica" });
  if (!d.estado_ficha) return el("span", { clase: "insignia neutra" }, icono("reloj"), "Sin ficha");
  return insignia(d.estado_ficha);
}

const celda = (clase, ...hijos) => el("td", { role: "cell", clase }, ...hijos);

function fila(d, i) {
  const foto = d.tipo === "foto";
  const principal = d.titular || d.nombre;
  const vista = foto
    ? el("button", { type: "button", clase: "boton-imagen miniatura-archivo",
      onclick: () => verFotoGuardada(d.documento_id, { titulo: principal, extra: [["Fecha de carga", fecha(d.fecha)]] }) },
      montura(d, { alt: d.texto_alternativo || `Foto ${d.nombre}`, diferida: i >= VISIBLES_SIN_DIFERIR }),
      el("span", { clase: "solo-lectores", texto: " (ver en grande)" }))
    : montura(d);
  const enlace = foto
    ? el("a", { clase: "documento-titular", href: `catalogar.html?doc=${encodeURIComponent(d.documento_id)}`, title: principal, texto: principal })
    : el("span", { clase: "documento-titular", title: principal, texto: principal });
  const [tipo, iconoTipo] = TIPOS[d.tipo] || [d.tipo, "info"];
  const nombreAccion = `Eliminar ${d.nombre}`;
  return el("tr", { role: "row", "data-documento": d.documento_id },
    celda("celda-foto", vista),
    el("th", { scope: "row", role: "rowheader", clase: "celda-documento" }, enlace, meta(d, principal)),
    celda("col-tipo", el("span", { clase: "insignia neutra" }, icono(iconoTipo), tipo)),
    celda("celda-estado", estadoFicha(d)),
    celda("celda-fecha", el("time", { datetime: d.fecha || null, texto: fecha(d.fecha) })),
    celda("col-acciones",
      el("button", { type: "button", clase: "boton-eliminar", "aria-label": nombreAccion, title: nombreAccion,
        onclick: (ev) => pedirConfirmacion(d, ev.currentTarget) }, icono("papelera"))));
}

/** Fila que ocupa toda la tabla (vacío o error). */
function filaAviso(contenido) {
  return el("tr", { role: "row", clase: "fila-aviso" }, el("td", { role: "cell", colspan: String(COLUMNAS) }, contenido));
}

function esqueletos() {
  const linea = (clase = "") => el("span", { clase: `esqueleto linea ${clase}`.trim() });
  filas.replaceChildren(...Array.from({ length: 6 }, () => el("tr", { role: "row", clase: "fila-cargando", "aria-hidden": "true" },
    celda("celda-foto", el("span", { clase: "montura" }, el("span", { clase: "esqueleto miniatura-esqueleto" }))),
    el("td", { role: "cell", clase: "celda-documento" }, linea(), linea("corta")),
    celda("col-tipo", linea()), celda("celda-estado", linea()), celda("celda-fecha", linea()), celda("col-acciones"))));
}

function sincronizarDireccion() {
  const p = new URLSearchParams(location.search);
  p.set("tipo", tipoActual());
  if (pagina > 1) p.set("pagina", pagina); else p.delete("pagina");
  history.replaceState(null, "", `${location.pathname}?${p}`);
}

function pintarPaginacion(texto, paginas) {
  for (const p of paginaciones) {
    if (!p.texto) continue;
    p.texto.textContent = texto;
    p.anterior.disabled = !texto || pagina <= 1;
    p.siguiente.disabled = !texto || pagina >= paginas;
  }
}

async function cargar() {
  const mio = ++turno;
  const tipo = tipoActual();
  const params = new URLSearchParams({ pagina, por_pagina: POR_PAGINA });
  if (tipo) params.set("tipo", tipo);
  tabla.dataset.filtro = tipo || "todos";
  tabla.setAttribute("aria-busy", "true");
  try {
    const { cuerpo } = await api(`/documentos?${params}`);
    if (mio !== turno) return;
    const paginas = Math.max(1, Math.ceil(cuerpo.total / POR_PAGINA));
    if (!cuerpo.documentos.length && pagina > 1) {   // p. ej. se borró el último de la última página
      pagina = paginas;
      if (cuerpo.total) { cargar(); return; }
    }
    estado.replaceChildren();
    const [uno, varios] = CONTEO[tipo] || CONTEO[""];
    pintarPaginacion(`Página ${numero(pagina)} de ${numero(paginas)} · ${numero(cuerpo.total)} ${cuerpo.total === 1 ? uno : varios}`, paginas);
    filas.replaceChildren(...(cuerpo.documentos.length ? cuerpo.documentos.map((d, i) => fila(d, i))
      : [filaAviso(el("p", { clase: "aviso-tabla" }, icono("info"), tipo === "norma" ? "No hay normas en el archivo."
        : tipo === "foto" ? "No hay fotos en el archivo todavía." : "El archivo está vacío."))]));
    sincronizarDireccion();
  } catch (e) {
    if (mio !== turno) return;
    mensaje(estado, e.message);
    pintarPaginacion("", 1);
    filas.replaceChildren(filaAviso(el("p", { clase: "aviso-tabla" }, icono("error"), "No se pudo leer el listado del archivo.")));
  } finally {
    if (mio === turno) tabla.removeAttribute("aria-busy");
  }
}

/** Cambia de vista (filtro o página): la confirmación abierta ya no aplica y su fila desaparece. */
function irA(nueva) {
  pagina = Math.max(1, nueva);
  alCerrar = null;
  cerrarConfirmacion();
  cargar();
}

for (const r of radios) r.addEventListener("change", () => irA(1));
const barra = document.querySelector(".barra-archivo");
paginaciones.forEach((p, i) => {
  // Desde la paginación de abajo, la página nueva se lee desde su principio
  const volverArriba = () => { if (i > 0) barra?.scrollIntoView({ block: "start" }); };
  p.anterior?.addEventListener("click", () => { irA(pagina - 1); volverArriba(); });
  p.siguiente?.addEventListener("click", () => { irA(pagina + 1); volverArriba(); });
});
esqueletos();
cargar();
