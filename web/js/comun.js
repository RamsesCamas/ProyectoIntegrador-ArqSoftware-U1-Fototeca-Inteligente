// Componentes comunes de la web: pie técnico plegable, gráficas SVG propias (sin bibliotecas) con su tabla
// equivalente y utilidades de formato.
import { el, insignia } from "./api.js";

export const CAPAS = {
  guardrails_entrada: "Guardrails de entrada", cache: "Caché", contexto: "Contexto (RAG)", enrutador: "Enrutador",
  modelo_vision: "Modelo de visión", modelo_composicion: "Modelo de composición", guardrails_salida: "Guardrails de salida",
  total: "Total",
};
// Paleta con contraste ≥ 3:1 sobre blanco (elementos gráficos, WCAG 1.4.11)
const COLORES = ["#0b5cad", "#1b6e3a", "#8a4b00", "#6b3fa0", "#b3261e", "#00707a", "#5c5f66"];
const SVG = "http://www.w3.org/2000/svg";

export const segundos = (ms) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`);
export const porcentaje = (x) => (x === null || x === undefined ? "—" : `${(x * 100).toFixed(1)} %`);

function svg(etiqueta, atributos = {}) {
  const nodo = document.createElementNS(SVG, etiqueta);
  for (const [k, v] of Object.entries(atributos)) nodo.setAttribute(k, v);
  return nodo;
}

export function textoGuardrail(g) {
  const v = g.valor !== undefined && g.valor !== null ? ` (${g.valor}${g.umbral !== undefined && g.umbral !== null ? ` / umbral ${g.umbral}` : ""})` : "";
  return `${g.verificacion}: ${g.resultado}${v}`;
}

/** Barra horizontal apilada en SVG con su tabla equivalente (etiqueta, valor y porcentaje del total). */
export function barraApilada(partes, { titulo = "Tiempo por capa", formato = segundos } = {}) {
  const total = partes.reduce((s, p) => s + p.valor, 0) || 1;
  const grafica = svg("svg", { viewBox: "0 0 100 8", preserveAspectRatio: "none", class: "barra-apilada",
    role: "img", "aria-label": `${titulo}: ${partes.map((p) => `${p.etiqueta} ${formato(p.valor)}`).join(", ")}` });
  let x = 0;
  partes.forEach((p, i) => {
    const w = (p.valor / total) * 100;
    const r = svg("rect", { x, y: 0, width: w, height: 8, fill: COLORES[i % COLORES.length] });
    const t = svg("title");
    t.textContent = `${p.etiqueta}: ${formato(p.valor)}`;
    r.append(t);
    grafica.append(r);
    x += w;
  });
  const tabla = el("table", { clase: "tabla tabla-compacta" },
    el("caption", { clase: "solo-lectores", texto: `${titulo} (tabla equivalente)` }),
    el("thead", {}, el("tr", {}, ["Capa", "Tiempo", "Proporción"].map((h) => el("th", { scope: "col", texto: h })))),
    el("tbody", {}, partes.map((p, i) => el("tr", {},
      el("th", { scope: "row" }, el("span", { clase: "muestra", style: `background:${COLORES[i % COLORES.length]}`, "aria-hidden": "true" }), p.etiqueta),
      el("td", { texto: formato(p.valor) }), el("td", { texto: porcentaje(p.valor / total) })))));
  return el("figure", { clase: "grafica" }, el("figcaption", { texto: titulo }), grafica, tabla);
}

/**
 * Gráfica de barras horizontales en SVG integrada en su tabla equivalente: cada fila lleva su barra (oculta a los
 * lectores de pantalla, que leen la tabla). `extras` agrega columnas de texto: [{ titulo, texto: (fila) => "…" }].
 */
export function barras(filas, { titulo, formato = (v) => String(v), maximo, encabezado = "Concepto", columnaValor = "Valor", extras = [] } = {}) {
  if (!filas.length) return el("figure", { clase: "grafica" }, el("figcaption", { texto: titulo }), el("p", { texto: "Sin datos todavía." }));
  const max = maximo ?? Math.max(1e-9, ...filas.map((f) => f.valor || 0));
  return el("figure", { clase: "grafica" }, el("figcaption", { texto: titulo }),
    el("div", { clase: "desplazable" }, el("table", { clase: "tabla-barras" },
      el("thead", {}, el("tr", {}, el("th", { scope: "col", texto: encabezado }),
        el("th", { scope: "col" }, el("span", { clase: "solo-lectores", texto: "Gráfica" })),
        el("th", { scope: "col", texto: columnaValor }), extras.map((x) => el("th", { scope: "col", texto: x.titulo })))),
      el("tbody", {}, filas.map((f) => {
        const barra = svg("svg", { viewBox: "0 0 100 10", preserveAspectRatio: "none", class: "barra-svg", "aria-hidden": "true", focusable: "false" });
        barra.append(svg("rect", { x: 0, y: 1, height: 8, width: Math.max(0.5, Math.min(100, ((f.valor || 0) / max) * 100)),
          fill: COLORES[(f.serie ?? 0) % COLORES.length] }));
        return el("tr", {}, el("th", { scope: "row", texto: f.etiqueta }), el("td", { clase: "celda-barra" }, barra),
          el("td", { clase: "valor", texto: formato(f.valor) }), extras.map((x) => el("td", { texto: x.texto(f) })));
      })))));
}

/** Pie técnico plegable para la demo de capas: traza, ruta, modelos, caché, guardrails, agente y tiempos. */
export function pieTecnico(meta) {
  if (!meta) return null;
  const tiempos = Object.entries(meta.tiempos_por_capa_ms || {}).filter(([, v]) => v > 0)
    .map(([k, v]) => ({ etiqueta: CAPAS[k] || k, valor: v }));
  const guardrails = [...(meta.guardrails?.entrada || []).map((g) => ["entrada", g]), ...(meta.guardrails?.salida || []).map((g) => ["salida", g])];
  const filas = [
    ["Traza", meta.traza_id], ["Ruta", meta.ruta],
    ["Modelos", Object.entries(meta.modelos || {}).map(([k, v]) => `${k}: ${v}`).join(" · ") || meta.modelo || "ninguno"],
    ["Caché", (meta.cache || "ninguna") + (meta.duplicado_de ? ` (duplicado de ${meta.duplicado_de.documento_id}, similitud ${meta.duplicado_de.similitud})` : "")],
    ["Iteraciones del agente", String(meta.iteraciones_agente ?? 0)],
    ["Tiempo total", meta.tiempo_ms !== undefined ? segundos(meta.tiempo_ms) : "—"],
    ["Versión de configuración", meta.version_configuracion],
  ];
  if (meta.razones_enrutador?.length) filas.push(["Enrutador", meta.razones_enrutador.join(" · ")]);
  return el("details", { clase: "pie-tecnico" },
    el("summary", { texto: "Pie técnico (capas, modelos y tiempos)" }),
    el("dl", {}, filas.flatMap(([k, v]) => [el("dt", { texto: k }), el("dd", { texto: v ?? "—" })])),
    tiempos.length ? barraApilada(tiempos, { titulo: "Tiempo por capa de esta petición" }) : null,
    guardrails.length ? el("table", { clase: "tabla tabla-compacta" },
      el("caption", { texto: "Guardrails aplicados" }),
      el("thead", {}, el("tr", {}, ["Etapa", "Verificación", "Resultado"].map((h) => el("th", { scope: "col", texto: h })))),
      el("tbody", {}, guardrails.map(([etapa, g]) => el("tr", {}, el("td", { texto: etapa }),
        el("th", { scope: "row", texto: g.verificacion }), el("td", { texto: textoGuardrail(g).slice(g.verificacion.length + 2) }))))) : null,
    meta.transiciones?.length ? el("p", { clase: "transiciones", texto: `Estados: ${meta.transiciones.join(" · ")}` }) : null);
}

export function mensaje(contenedor, texto, tipo = "error") {
  contenedor.replaceChildren(el("div", { clase: `mensaje ${tipo}`, role: tipo === "error" ? "alert" : "status", texto }));
}

export { insignia };
