// Archivo: GET /api/documentos (paginado, con filtro por tipo) y DELETE /api/documentos/{id} con confirmación en la
// página (sin window.confirm). El listado trae `titular` y `texto_alternativo` de cada ficha (null si no tiene): el
// titular y el `alt` de la miniatura salen de ahí, con una sola petición por página.
import { api, anunciar, el, insignia } from "./api.js";
import { mensaje, miniatura, numero, verFotoGuardada } from "./comun.js";
import { icono } from "./iconos.js";

const POR_PAGINA = 24;
const VISIBLES_SIN_DIFERIR = 8;   // filas que suelen verse sin desplazarse: sus miniaturas no se difieren
const COLUMNAS = 6;
const TIPOS = { foto: ["Foto", "foto"], norma: ["Norma", "regla"] };
const parametros = new URLSearchParams(location.search);
let pagina = Math.max(1, Number(parametros.get("pagina")) || 1);
const estado = document.getElementById("estado");
const confirmacion = document.getElementById("confirmacion");
const filas = document.getElementById("filas");
const textoPagina = document.getElementById("pagina");
const anterior = document.getElementById("anterior");
const siguiente = document.getElementById("siguiente");
const radios = [...document.querySelectorAll('#filtro-tipo input[name="tipo"]')];
if (parametros.has("tipo")) {
  const elegido = radios.find((r) => r.value === parametros.get("tipo"));
  if (elegido) elegido.checked = true;
}
const tipoActual = () => radios.find((r) => r.checked)?.value ?? "foto";
let alCerrar = null;
let turno = 0;

const fecha = (iso) => (iso || "").slice(0, 10);

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
      el("p", { clase: "confirmacion-documento" }, el("strong", { texto: titulo }),
        el("span", { clase: "documento-meta" }, titulo !== doc.nombre ? `${doc.nombre} · ` : "", el("span", { clase: "id", texto: doc.documento_id }))),
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

function fila(d, i) {
  const foto = d.tipo === "foto";
  const titular = d.titular || null;
  const principal = titular || d.nombre;
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
  return el("tr", { "data-documento": d.documento_id },
    el("td", { clase: "celda-foto" }, vista),
    el("th", { scope: "row", clase: "celda-documento" }, enlace,
      el("span", { clase: "documento-meta" }, titular ? `${d.nombre} · ` : "", el("span", { clase: "id", texto: d.documento_id }))),
    el("td", {}, el("span", { clase: "insignia neutra" }, icono(iconoTipo), tipo)),
    el("td", {}, estadoFicha(d)),
    el("td", { clase: "fecha" }, el("time", { datetime: d.fecha || null, texto: fecha(d.fecha) || "—" })),
    el("td", { clase: "col-acciones" },
      el("button", { type: "button", clase: "boton fantasma peligro", "aria-label": `Eliminar ${d.nombre}`,
        onclick: (ev) => pedirConfirmacion(d, ev.currentTarget) }, icono("papelera"), "Eliminar")));
}

/** Fila que ocupa toda la tabla (vacío o error). */
function filaAviso(contenido) {
  return el("tr", { clase: "fila-aviso" }, el("td", { colspan: String(COLUMNAS) }, contenido));
}

function esqueletos() {
  const linea = (clase = "") => el("span", { clase: `esqueleto linea ${clase}`.trim() });
  filas.replaceChildren(...Array.from({ length: 6 }, () => el("tr", { clase: "fila-cargando", "aria-hidden": "true" },
    el("td", { clase: "celda-foto" }, el("span", { clase: "montura" }, el("span", { clase: "esqueleto miniatura-esqueleto" }))),
    el("td", { clase: "celda-documento" }, linea(), linea("corta")),
    el("td", {}, linea()), el("td", {}, linea()), el("td", {}, linea()), el("td", {}))));
}

function sincronizarDireccion() {
  const p = new URLSearchParams(location.search);
  p.set("tipo", tipoActual());
  if (pagina > 1) p.set("pagina", pagina); else p.delete("pagina");
  history.replaceState(null, "", `${location.pathname}?${p}`);
}

async function cargar() {
  const mio = ++turno;
  const tipo = tipoActual();
  const params = new URLSearchParams({ pagina, por_pagina: POR_PAGINA });
  if (tipo) params.set("tipo", tipo);
  filas.closest("table").setAttribute("aria-busy", "true");
  try {
    const { cuerpo } = await api(`/documentos?${params}`);
    if (mio !== turno) return;
    const paginas = Math.max(1, Math.ceil(cuerpo.total / POR_PAGINA));
    if (!cuerpo.documentos.length && pagina > 1) {   // p. ej. se borró el último de la última página
      pagina = paginas;
      if (cuerpo.total) { cargar(); return; }
    }
    estado.replaceChildren();
    textoPagina.textContent = `Página ${numero(pagina)} de ${numero(paginas)} · ${numero(cuerpo.total)} ${cuerpo.total === 1 ? "documento" : "documentos"}`;
    anterior.disabled = pagina <= 1;
    siguiente.disabled = pagina >= paginas;
    filas.replaceChildren(...(cuerpo.documentos.length ? cuerpo.documentos.map((d, i) => fila(d, i))
      : [filaAviso(el("p", { clase: "aviso-tabla" }, icono("info"), tipo === "norma" ? "No hay normas en el archivo."
        : tipo === "foto" ? "No hay fotos en el archivo todavía." : "El archivo está vacío."))]));
    sincronizarDireccion();
  } catch (e) {
    if (mio !== turno) return;
    mensaje(estado, e.message);
    textoPagina.textContent = "";
    filas.replaceChildren(filaAviso(el("p", { clase: "aviso-tabla" }, icono("error"), "No se pudo leer el listado del archivo.")));
  } finally {
    if (mio === turno) filas.closest("table").removeAttribute("aria-busy");
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
anterior.addEventListener("click", () => irA(pagina - 1));
siguiente.addEventListener("click", () => irA(pagina + 1));
esqueletos();
cargar();
