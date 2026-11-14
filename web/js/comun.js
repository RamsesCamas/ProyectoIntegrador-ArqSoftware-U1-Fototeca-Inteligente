// Componentes comunes de la web: pie técnico plegable, gráficas SVG propias (sin bibliotecas) con su tabla
// equivalente, visor de fotos, mensajes, medidor, tipos de fuente y utilidades de formato. Los colores NO viven aquí:
// cada serie es una clase .serie-N y cada componente una clase de css/base.css (tokens --…).
import { api, el, insignia } from "./api.js";
import { icono } from "./iconos.js";

export const CAPAS = {
  guardrails_entrada: "Guardrails de entrada", cache: "Caché", contexto: "Contexto (RAG)", enrutador: "Enrutador",
  modelo_vision: "Modelo de visión", modelo_composicion: "Modelo de composición", guardrails_salida: "Guardrails de salida",
  total: "Total",
};
/** Orden en que una ficha recorre las capas (para listas y barras apiladas). */
export const ORDEN_CAPAS = ["guardrails_entrada", "cache", "contexto", "enrutador", "modelo_vision", "modelo_composicion", "guardrails_salida"];
/**
 * Serie de color por CLAVE de capa: la misma capa tiene el mismo color en todas las gráficas. La serie 5 (rojo) se
 * reserva para «bloqueada» y errores; la 1 es la serie por defecto.
 */
export const SERIE_CAPA = {
  guardrails_entrada: 4, guardrails_salida: 4, cache: 6, contexto: 3, enrutador: 7, modelo_vision: 2, modelo_composicion: 8, total: 1,
};
export const claseSerie = (n) => `serie-${Number.isInteger(n) && n >= 1 && n <= 8 ? n : 1}`;
// Color por significado: las barras de datos son neutras (serie 1, gris) salvo que se pida una serie explícita; el
// color por CLAVE de capa solo se usa en la barra apilada, donde las partes sí suman (los tiempos de UNA petición).
const serieDe = (f) => f.serie ?? SERIE_CAPA[f.clave] ?? 1;
const serieBarra = (f) => f.serie ?? 1;
const SVG = "http://www.w3.org/2000/svg";

export const segundos = (ms) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : ms > 0 && ms < 1 ? "< 1 ms" : `${Math.round(ms)} ms`);
export const porcentaje = (x) => (x === null || x === undefined ? "—" : `${(x * 100).toFixed(1)} %`);
export const numero = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("es-MX"));
/** Duración legible para personas: «37 s», «1 min 05 s», «2 h 10 min». */
export function duracion(s) {
  const t = Math.max(0, Math.round(s));
  if (t < 60) return `${t} s`;
  if (t < 3600) return `${Math.floor(t / 60)} min ${String(t % 60).padStart(2, "0")} s`;
  return `${Math.floor(t / 3600)} h ${Math.floor((t % 3600) / 60)} min`;
}

function svg(etiqueta, atributos = {}) {
  const nodo = document.createElementNS(SVG, etiqueta);
  for (const [k, v] of Object.entries(atributos)) nodo.setAttribute(k, v);
  return nodo;
}

export function textoGuardrail(g) {
  const v = g.valor !== undefined && g.valor !== null ? ` (${g.valor}${g.umbral !== undefined && g.umbral !== null ? ` / umbral ${g.umbral}` : ""})` : "";
  return `${g.verificacion}: ${g.resultado}${v}`;
}

/**
 * Barra horizontal apilada en SVG con su tabla equivalente (etiqueta, valor y porcentaje del total).
 * Cada parte: { etiqueta, valor, clave? (capa), serie? }.
 */
export function barraApilada(partes, { titulo = "Tiempo por capa", formato = segundos } = {}) {
  const total = partes.reduce((s, p) => s + p.valor, 0) || 1;
  // Sin viewBox: x y ancho en % del ancho real (los extremos redondeados los da el CSS, sin deformarse)
  const grafica = svg("svg", { class: "barra-apilada",
    role: "img", "aria-label": `${titulo}: ${partes.map((p) => `${p.etiqueta} ${formato(p.valor)}`).join(", ")}` });
  let x = 0;
  partes.forEach((p) => {
    const w = (p.valor / total) * 100;
    const r = svg("rect", { x: `${x.toFixed(3)}%`, y: 0, width: `${w.toFixed(3)}%`, height: "100%", class: claseSerie(serieDe(p)) });
    const t = svg("title");
    t.textContent = `${p.etiqueta}: ${formato(p.valor)}`;
    r.append(t);
    grafica.append(r);
    x += w;
  });
  const tabla = el("table", { clase: "tabla tabla-compacta" },
    el("caption", { clase: "solo-lectores", texto: `${titulo} (tabla equivalente)` }),
    el("thead", {}, el("tr", {}, el("th", { scope: "col", texto: "Capa" }), el("th", { scope: "col", clase: "num", texto: "Tiempo" }),
      el("th", { scope: "col", clase: "num", texto: "Proporción" }))),
    el("tbody", {}, partes.map((p) => el("tr", {},
      el("th", { scope: "row" }, el("span", { clase: `muestra ${claseSerie(serieDe(p))}`, "aria-hidden": "true" }), p.etiqueta),
      el("td", { clase: "num", texto: formato(p.valor) }), el("td", { clase: "num", texto: porcentaje(p.valor / total) })))));
  return el("figure", { clase: "grafica" }, el("figcaption", { texto: titulo }), grafica, tabla);
}

/**
 * Gráfica de barras horizontales en SVG integrada en su tabla equivalente: cada fila lleva su barra (oculta a los
 * lectores de pantalla, que leen la tabla). `extras` agrega columnas de texto: [{ titulo, texto: (fila) => "…" }].
 * Cada fila: { etiqueta, valor, clave? (capa), serie? }.
 */
export function barras(filas, { titulo, formato = (v) => numero(v), maximo, encabezado = "Concepto", columnaValor = "Valor", extras = [] } = {}) {
  if (!filas.length) return el("figure", { clase: "grafica" }, el("figcaption", { texto: titulo }), el("p", { clase: "suave", texto: "Sin datos todavía." }));
  const max = maximo ?? Math.max(1e-9, ...filas.map((f) => f.valor || 0));
  return el("figure", { clase: "grafica" }, el("figcaption", { texto: titulo }),
    el("div", { clase: "desplazable" }, el("table", { clase: "tabla-barras" },
      el("thead", {}, el("tr", {}, el("th", { scope: "col", texto: encabezado }),
        el("th", { scope: "col" }, el("span", { clase: "solo-lectores", texto: "Gráfica" })),
        el("th", { scope: "col", clase: "num", texto: columnaValor }), extras.map((x) => el("th", { scope: "col", clase: "num", texto: x.titulo })))),
      el("tbody", {}, filas.map((f) => {
        // Sin viewBox (unidades en px, anchos en % del real): pista al 100 %, rejilla tenue a 25/50/75 % y la barra
        // con extremos redondeados encima
        const barra = svg("svg", { class: "barra-svg", "aria-hidden": "true", focusable: "false" });
        barra.append(svg("rect", { class: "pista", x: 0, y: 3, width: "100%", height: 10, rx: 2 }));
        for (const x of ["25%", "50%", "75%"]) barra.append(svg("line", { class: "rejilla-linea", x1: x, x2: x, y1: 0, y2: 16 }));
        const ancho = Math.max(0.5, Math.min(100, ((f.valor || 0) / max) * 100));
        barra.append(svg("rect", { x: 0, y: 3, height: 10, rx: 2, width: `${ancho.toFixed(2)}%`, class: claseSerie(serieBarra(f)) }));
        return el("tr", {}, el("th", { scope: "row", texto: f.etiqueta }), el("td", { clase: "celda-barra" }, barra),
          el("td", { clase: "valor num", texto: formato(f.valor) }), extras.map((x) => el("td", { clase: "num", texto: x.texto(f) })));
      })))));
}

/** Resumen de una línea para el summary del pie técnico: «ruta · caché · iteraciones · tiempo». */
export function resumenTecnico(meta) {
  return [
    meta.ruta ? `ruta: ${meta.ruta}` : null,
    `caché: ${meta.cache || "ninguna"}`,
    `iteraciones: ${meta.iteraciones_agente ?? 0}`,
    meta.tiempo_ms !== undefined && meta.tiempo_ms !== null ? segundos(meta.tiempo_ms) : null,
  ].filter(Boolean).join(" · ");
}

/** Pie técnico plegable para la demo de capas: traza, ruta, modelos, caché, guardrails, agente y tiempos. */
export function pieTecnico(meta) {
  if (!meta) return null;
  const tiempos = Object.entries(meta.tiempos_por_capa_ms || {}).filter(([, v]) => v > 0)
    .map(([k, v]) => ({ clave: k, etiqueta: CAPAS[k] || k, valor: v }));
  const guardrails = [...(meta.guardrails?.entrada || []).map((g) => ["entrada", g]), ...(meta.guardrails?.salida || []).map((g) => ["salida", g])];
  const filas = [
    ["Traza", meta.traza_id], ["Ruta", meta.ruta],
    ["Modelos", Object.entries(meta.modelos || {}).map(([k, v]) => `${k}: ${v}`).join(" · ") || meta.modelo || "ninguno"],
    ["Caché", (meta.cache || "ninguna") + (meta.duplicado_de ? ` (duplicado de ${meta.duplicado_de.documento_id}, similitud ${meta.duplicado_de.similitud})` : "")],
    ["Iteraciones del agente", String(meta.iteraciones_agente ?? 0)],
    ["Tiempo total", meta.tiempo_ms !== undefined && meta.tiempo_ms !== null ? segundos(meta.tiempo_ms) : "—"],
    ["Versión de configuración", meta.version_configuracion],
  ];
  if (meta.razones_enrutador?.length) filas.push(["Enrutador", meta.razones_enrutador.join(" · ")]);
  return el("details", { clase: "pie-tecnico" },
    el("summary", {}, icono("cpu"), el("span", { clase: "pie-tecnico-titulo", texto: "Pie técnico" }),
      el("span", { clase: "resumen-tecnico", texto: resumenTecnico(meta) })),
    el("div", { clase: "pie-tecnico-cuerpo" },
      el("dl", {}, filas.flatMap(([k, v]) => [el("dt", { texto: k }), el("dd", { clase: k === "Traza" ? "id" : null, texto: v ?? "—" })])),
      tiempos.length ? barraApilada(tiempos, { titulo: "Tiempo por capa de esta petición" }) : null,
      guardrails.length ? el("div", { clase: "desplazable" }, el("table", { clase: "tabla tabla-compacta" },
        el("caption", { texto: "Guardrails aplicados" }),
        el("thead", {}, el("tr", {}, ["Etapa", "Verificación", "Resultado"].map((h) => el("th", { scope: "col", texto: h })))),
        el("tbody", {}, guardrails.map(([etapa, g]) => el("tr", {}, el("td", { texto: etapa }),
          el("th", { scope: "row", texto: g.verificacion }), el("td", { texto: textoGuardrail(g).slice(g.verificacion.length + 2) })))))) : null,
      meta.transiciones?.length ? el("p", { clase: "transiciones", texto: `Estados: ${meta.transiciones.join(" · ")}` }) : null));
}

const ICONO_MENSAJE = { ok: "check", info: "info", aviso: "alerta", error: "error" };

/**
 * Nodo de mensaje con su icono a la izquierda. Tipos: error (role=alert), ok, info (progreso, conteos y estados
 * vacíos) y aviso. `contenido` es texto o nodos (p. ej. un párrafo y una lista).
 */
export function crearMensaje(contenido, tipo = "error") {
  return el("div", { clase: `mensaje ${tipo} con-icono`, role: tipo === "error" ? "alert" : "status" },
    icono(ICONO_MENSAJE[tipo] || "info", "mensaje-icono"), el("div", { clase: "mensaje-texto" }, contenido));
}

/** Mensaje en un contenedor (reemplaza lo que hubiera). */
export function mensaje(contenedor, texto, tipo = "error") {
  contenedor.replaceChildren(crearMensaje(texto, tipo));
}

/**
 * Medidor «valor/límite» (p. ej. el texto alternativo: 0–250). Color por umbral MÁS texto: hasta `aviso` (fracción
 * del límite) es ok; desde ahí, aviso; por encima del límite, error. La barra es decorativa; el texto lo dice todo.
 */
export function medidor(valor, limite, { aviso = 0.9, unidad = "caracteres", id = null } = {}) {
  const fraccion = limite > 0 ? valor / limite : 0;
  const nivel = fraccion > 1 ? "error" : fraccion >= aviso ? "aviso" : "ok";
  const relleno = el("span", { clase: "medidor-relleno" });
  relleno.style.width = `${Math.min(100, fraccion * 100).toFixed(1)}%`;
  return el("div", { clase: "medidor", "data-nivel": nivel, id },
    el("span", { clase: "medidor-barra", "aria-hidden": "true" }, relleno),
    el("span", { clase: "medidor-texto", texto: `${numero(valor)}/${numero(limite)}${unidad ? ` ${unidad}` : ""}` }));
}

/**
 * Tipos de fuente de la ficha (trazabilidad): el mismo icono, clase de color y etiqueta en toda la web.
 * `claseChip` conserva las clases de los chips existentes (.chip-foto para las fotos similares).
 */
export const FUENTES = {
  referencia_humana: { etiqueta: "Referencia humana", icono: "referencia", claseChip: "chip-referencia_humana" },
  foto_similar: { etiqueta: "Foto similar", icono: "foto-similar", claseChip: "chip-foto" },
  regla: { etiqueta: "Regla", icono: "regla", claseChip: "chip-regla" },
  tesauro: { etiqueta: "Tesauro", icono: "tesauro", claseChip: "chip-tesauro" },
  archivista: { etiqueta: "Archivista", icono: "archivista", claseChip: "chip-archivista" },
  etiqueta_open_images: { etiqueta: "Etiqueta de Open Images", icono: "etiqueta", claseChip: "chip-etiqueta_open_images" },
};
const FUENTE_GENERICA = { etiqueta: "Otra fuente", icono: "info", claseChip: "" };
export const fuente = (tipo) => FUENTES[tipo] || { ...FUENTE_GENERICA, etiqueta: tipo || FUENTE_GENERICA.etiqueta };

/** Leyenda de los tipos de fuente con cuántas citas hay de cada uno: { tipo: n }. Los tipos sin citas no aparecen. */
export function leyendaFuentes(conteos) {
  const tipos = Object.keys(FUENTES).filter((t) => conteos[t]).concat(Object.keys(conteos).filter((t) => !FUENTES[t] && conteos[t]));
  return el("ul", { clase: "leyenda-fuentes", "aria-label": "Tipos de fuente de la ficha" }, tipos.map((t) => {
    const f = fuente(t);
    return el("li", {}, el("span", { clase: `chip ${f.claseChip}` }, icono(f.icono), f.etiqueta),
      el("span", { clase: "conteo", texto: `${numero(conteos[t])} ${conteos[t] === 1 ? "cita" : "citas"}` }));
  }));
}

/** Ejecuta `fn` ahora si la pestaña está visible, o en cuanto vuelva a estarlo (no se piden datos en segundo plano). */
export function cuandoVisible(fn) {
  if (!document.hidden) { fn(); return; }
  const alVolver = () => {
    if (document.hidden) return;
    document.removeEventListener("visibilitychange", alVolver);
    fn();
  };
  document.addEventListener("visibilitychange", alVolver);
}

// ── Visor de fotos ──
// Un <dialog> modal para ver una foto en grande junto con lo que el archivo guardó de ella. Esc o «Cerrar» lo cierran
// y el foco vuelve al control que lo abrió. Solo usa la API de la web (R8): la miniatura y GET /fichas/{id}.
const NOMBRES_METADATOS = {
  gps: "GPS", numero_serie: "número de serie de la cámara", autor: "autor", exif_completo: "EXIF completo",
  xmp: "bloque XMP", iptc_photoshop: "bloque IPTC/Photoshop", metadatos_png: "metadatos del PNG",
};
let visor = null;
let turnoVisor = 0;

function crearVisor() {
  const dialogo = el("dialog", { id: "visor", clase: "visor", "aria-labelledby": "visor-titulo" },
    el("div", { clase: "visor-cabecera" },
      icono("lupa-foto", "visor-icono"),
      el("h2", { id: "visor-titulo" }),
      el("button", { type: "button", clase: "boton fantasma", onclick: () => dialogo.close() }, icono("cerrar"), "Cerrar")),
    el("div", { clase: "visor-cuerpo" },
      el("figure", {}, el("img", { id: "visor-imagen", alt: "" }), el("figcaption", { id: "visor-medidas" })),
      el("div", { clase: "visor-panel" }, el("dl", { id: "visor-datos" }), el("div", { id: "visor-extra", clase: "visor-extra" }))));
  // Un clic fuera de la caja (sobre el fondo) también cierra
  dialogo.addEventListener("click", (ev) => { if (ev.target === dialogo) dialogo.close(); });
  dialogo.addEventListener("close", () => {
    const origen = dialogo.origen;
    dialogo.origen = null;
    if (origen?.isConnected) origen.focus();
  });
  document.body.append(dialogo);
  return dialogo;
}

// Identificadores técnicos (mono, pueden partirse en cualquier punto) y cifras o valores técnicos (mono)
const DATOS_ID = new Set(["Documento", "Traza", "Fragmento"]);
const DATOS_MONO = new Set(["Ruta", "Similitud", "Puntaje", "Puntaje de recuperación", "Medidas originales", "Tamaño", "Tipo",
  "Fecha de carga"]);

/** Pinta los pares [etiqueta, valor] del visor. El valor puede ser texto o un nodo (p. ej. una insignia de estado). */
function pintarDatos(datos) {
  visor.querySelector("#visor-datos").replaceChildren(...datos
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .flatMap(([k, v]) => [el("dt", { texto: k }),
      el("dd", { clase: DATOS_ID.has(k) ? "id" : DATOS_MONO.has(k) ? "mono" : null }, v instanceof Node ? v : String(v))]));
}

/** Abre el visor. `datos` es una lista de pares [etiqueta, valor]; `enlace` = { href, texto } abre en otra pestaña. */
export function abrirVisor({ src, alt, titulo, datos = [], nota = "", enlace = null }) {
  visor ||= crearVisor();
  const turno = ++turnoVisor;
  const img = visor.querySelector("#visor-imagen");
  const medidas = visor.querySelector("#visor-medidas");
  visor.querySelector("#visor-titulo").textContent = titulo;
  medidas.textContent = "Cargando la imagen…";
  // El pie dice la verdad sobre la escala: la imagen nunca se amplía (base.css) y, si no cabe, se reduce
  img.onload = () => {
    const ancho = img.getBoundingClientRect().width;
    const escala = ancho && ancho < img.naturalWidth - 1 ? `se muestra al ${Math.round((ancho / img.naturalWidth) * 100)} %` : "a tamaño real";
    medidas.textContent = `Imagen de ${img.naturalWidth} × ${img.naturalHeight} px, ${escala}. ${nota}`.trim();
  };
  img.onerror = () => { medidas.textContent = "No se pudo cargar la imagen."; };
  img.alt = alt || titulo;
  img.removeAttribute("src");
  img.src = src;
  pintarDatos(datos);
  visor.querySelector("#visor-extra").replaceChildren(...(enlace ? [el("p", {},
    el("a", { href: enlace.href, target: "_blank", rel: "noopener" }, enlace.texto, icono("externo", "icono-16"),
      el("span", { clase: "solo-lectores", texto: " (se abre en otra pestaña)" })))] : []));
  if (!visor.open) {
    visor.origen = document.activeElement;
    visor.showModal();
  }
  return {
    vigente: () => turno === turnoVisor && visor.open,
    actualizar: (nuevos, nuevoAlt) => {
      if (turno !== turnoVisor) return;
      pintarDatos(nuevos);
      if (nuevoAlt) img.alt = nuevoAlt;
    },
  };
}

/** Metadatos que el guardrail `exif_privacidad` quitó al guardar la foto (si la respuesta trae esa verificación). */
export function metadatosQuitados(meta) {
  const g = (meta?.guardrails?.entrada || []).find((x) => x.verificacion === "exif_privacidad");
  if (!g) return null;
  const quitados = g.detalle?.eliminado || [];
  return quitados.length ? quitados.map((q) => NOMBRES_METADATOS[q] || q).join(", ")
    : "ninguno (la foto no traía GPS, número de serie ni autor)";
}

function datosDeFicha(doc, ficha, extra) {
  return [
    ["Documento", doc],
    ...extra,
    ["Estado de la ficha", ficha ? insignia(ficha.estado) : "Sin ficha todavía"],
    ["Titular", ficha?.titular],
    ["Texto alternativo", ficha?.texto_alternativo],
    ["Descripción", ficha?.descripcion],
    ["Palabras clave", (ficha?.palabras_clave || []).map((p) => p.termino).join(", ")],
  ];
}

/**
 * Ve en grande una foto del archivo con lo que se guardó de ella. Si no se pasa `ficha`, la pide a GET /fichas/{id}.
 * `extra` agrega filas [etiqueta, valor] después del documento.
 */
export async function verFotoGuardada(doc, { titulo = "Foto del archivo", ficha = null, extra = [], enlaceFicha = true } = {}) {
  const v = abrirVisor({
    src: `/api/fotos/${encodeURIComponent(doc)}/miniatura?lado=512`,
    alt: ficha?.texto_alternativo || `Foto ${doc}`,
    titulo,
    datos: ficha ? datosDeFicha(doc, ficha, extra) : [["Documento", doc], ...extra, ["Ficha", "Cargando…"]],
    nota: "Es la copia para la web que guarda el archivo: 512 px como máximo y sin metadatos EXIF.",
    enlace: enlaceFicha ? { href: `catalogar.html?doc=${encodeURIComponent(doc)}`, texto: "Abrir su ficha completa" } : null,
  });
  if (ficha) return;
  try {
    const { cuerpo } = await api(`/fichas/${encodeURIComponent(doc)}`, { aceptar: [404] });
    v.actualizar(datosDeFicha(doc, cuerpo?.ficha || null, extra), cuerpo?.ficha?.texto_alternativo);
  } catch (e) {
    v.actualizar([["Documento", doc], ...extra, ["Ficha", `No se pudo leer: ${e.message}`]]);
  }
}

/** Miniatura de una foto del archivo con medidas reservadas (sin saltos de diseño) y carga diferida opcional. */
export function miniatura(doc, { alt, lado = 256, ancho = 256, alto = 192, diferida = false, doble = true } = {}) {
  const base = `/api/fotos/${encodeURIComponent(doc)}/miniatura?lado=`;
  return el("img", { src: `${base}${lado}`, srcset: doble ? `${base}${lado} 1x, ${base}${lado * 2} 2x` : null, alt,
    width: String(ancho), height: String(alto), loading: diferida ? "lazy" : null, decoding: "async" });
}

export { insignia };
