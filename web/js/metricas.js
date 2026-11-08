// Métricas: GET /api/metricas y GET /api/configuracion. Gráficas SVG propias, cada una con su tabla equivalente.
import { anunciar, api, el } from "./api.js";
import { barraApilada, barras, CAPAS, mensaje, porcentaje, segundos } from "./comun.js";

const SERIE_RESULTADO = { aprobada: 1, sanitizado: 2, marcada: 3, bloqueada: 4 };
const FLUJOS = { fichas: "Fichas", busquedas: "Búsquedas" };
const ms = (v) => segundos(v || 0);

function tarjeta(titulo, ...hijos) {
  return el("section", { clase: "tarjeta" }, el("h2", { texto: titulo }), ...hijos);
}

function latenciaPorEtapa(m) {
  const flujos = Object.entries(m.latencia_por_capa || {});
  if (!flujos.length) return [el("p", { texto: "Sin fichas ni búsquedas todavía." })];
  return flujos.map(([flujo, etapas]) => {
    const partes = Object.entries(etapas).filter(([c, v]) => c !== "total" && v.n && v.p50_ms > 0)
      .map(([c, v]) => ({ etiqueta: CAPAS[c] || c, valor: v.p50_ms }));
    const total = etapas.total;
    return el("div", {},
      el("h3", { texto: `${FLUJOS[flujo] || flujo}${total?.n ? ` · total p50 ${ms(total.p50_ms)}, p95 ${ms(total.p95_ms)} (n=${total.n})` : ""}` }),
      partes.length ? barraApilada(partes, { titulo: `${FLUJOS[flujo] || flujo}: tiempo p50 por capa (barras apiladas)` }) : null,
      barras(Object.entries(etapas).map(([c, v]) => ({ etiqueta: CAPAS[c] || c, valor: v.p95_ms || 0, n: v.n, p50: v.p50_ms })),
        { titulo: `${FLUJOS[flujo] || flujo}: p50 y p95 por capa`, encabezado: "Capa", columnaValor: "p95", formato: ms,
          extras: [{ titulo: "p50", texto: (f) => ms(f.p50) }, { titulo: "n", texto: (f) => String(f.n) }] }));
  });
}

function latenciaPorCapaArquitectura(m) {
  const filas = Object.entries(m.latencia_por_evento || {}).flatMap(([capa, eventos]) =>
    Object.entries(eventos).map(([evento, v]) => ({ etiqueta: `${capa} · ${evento}`, valor: v.p50_ms || 0, p95: v.p95_ms, n: v.n })));
  return barras(filas, { titulo: "p50 y p95 por capa (C1–C7, T1, T2) y evento", encabezado: "Capa · evento", columnaValor: "p50",
    formato: ms, extras: [{ titulo: "p95", texto: (f) => ms(f.p95) }, { titulo: "n", texto: (f) => String(f.n) }] });
}

async function cargar() {
  const horas = document.getElementById("desde").value;
  const desde = horas ? new Date(Date.now() - Number(horas) * 3600 * 1000).toISOString() : "";
  const estado = document.getElementById("estado");
  const panel = document.getElementById("panel");
  panel.setAttribute("aria-busy", "true");
  try {
    const [{ cuerpo: m }, { cuerpo: conf }] = await Promise.all([
      api(`/metricas${desde ? `?desde=${encodeURIComponent(desde)}` : ""}`), api("/configuracion")]);
    const a = m.accesibilidad || {};
    const r = m.retroalimentacion || {};
    const guardrails = [...(m.guardrails || [])].sort((x, y) => y.n - x.n);
    panel.replaceChildren(
      tarjeta("Accesibilidad del archivo",
        el("p", { clase: "cifra", texto: porcentaje(a.porcentaje_alt_validado) }),
        el("p", { texto: `de ${a.fotos ?? 0} fotos tienen texto alternativo validado · ${a.fichas_validadas ?? 0} fichas validadas · `
          + `${porcentaje(a.porcentaje_requiere_revision)} requieren revisión · ${porcentaje(a.porcentaje_sin_ficha)} sin ficha` }),
        barras([{ etiqueta: "Texto alternativo validado", valor: a.alt_validado || 0, serie: 1 },
          { etiqueta: "Borrador", valor: a.borrador || 0, serie: 0 },
          { etiqueta: "Requiere revisión", valor: a.requiere_revision || 0, serie: 2 },
          { etiqueta: "Sin ficha", valor: a.sin_ficha || 0, serie: 6 }],
        { titulo: "Fotos por estado de su ficha", maximo: a.fotos || 1, encabezado: "Estado", columnaValor: "Fotos" })),
      tarjeta("Latencia por capa", ...latenciaPorEtapa(m), latenciaPorCapaArquitectura(m)),
      tarjeta("Caché",
        barras(Object.entries(m.cache || {}).map(([k, v]) => ({ etiqueta: FLUJOS[k] || k, valor: v.tasa_aciertos || 0, ...v })),
          { titulo: "Tasa de aciertos por espacio", encabezado: "Espacio", columnaValor: "Tasa", formato: porcentaje, maximo: 1,
            extras: [{ titulo: "Consultas", texto: (f) => String(f.consultas) }, { titulo: "Exactos", texto: (f) => String(f.aciertos_exactos) },
              { titulo: "Semánticos", texto: (f) => String(f.aciertos_semanticos) }] })),
      tarjeta("Guardrails",
        barras(guardrails.map((g) => ({ etiqueta: `${g.verificacion} · ${g.resultado}`, valor: g.n, serie: SERIE_RESULTADO[g.resultado] ?? 0 })),
          { titulo: "Activaciones por verificación y resultado", encabezado: "Verificación · resultado", columnaValor: "Activaciones" })),
      tarjeta("Uso por modelo",
        barras(Object.entries(m.modelos || {}).map(([k, v]) => ({ etiqueta: k, valor: v.llamadas, ...v })),
          { titulo: "Llamadas por modelo", encabezado: "Modelo", columnaValor: "Llamadas",
            extras: [{ titulo: "Tokens de entrada", texto: (f) => String(f.tokens_prompt) }, { titulo: "Tokens de salida", texto: (f) => String(f.tokens_salida) },
              { titulo: "Tiempo", texto: (f) => ms(f.tiempo_ms) }, { titulo: "Respaldos", texto: (f) => String(f.respaldos) },
              { titulo: "Tiempos agotados", texto: (f) => String(f.tiempos_agotados) }, { titulo: "JSON inválido", texto: (f) => String(f.json_invalido) }] })),
      tarjeta("Enrutador y agente",
        barras(Object.entries(m.rutas || {}).map(([k, v]) => {
          const [flujo, ruta] = k.split(":");
          return { etiqueta: `${FLUJOS[flujo] || flujo} · ${ruta}`, valor: v };
        }), { titulo: "Rutas elegidas", encabezado: "Flujo · ruta", columnaValor: "Veces" }),
        barras(Object.entries(m.iteraciones_agente || {}).map(([k, v]) => ({ etiqueta: `${k} iteraciones`, valor: v })),
          { titulo: "Iteraciones del ciclo de agente por ficha", encabezado: "Iteraciones", columnaValor: "Fichas" }),
        barras(Object.entries(m.iteraciones_agente_busquedas || {}).map(([k, v]) => ({ etiqueta: `${k} reformulaciones`, valor: v })),
          { titulo: "Reformulaciones por búsqueda", encabezado: "Reformulaciones", columnaValor: "Búsquedas" })),
      tarjeta("Retroalimentación",
        el("p", { texto: `${r.total ?? 0} opiniones · ${r.util ?? 0} útiles · ${r.no_util ?? 0} no útiles · tasa útil ${porcentaje(r.tasa_util)} · `
          + `${r.con_comentario ?? 0} con comentario · ${r.fichas_validadas ?? 0} fichas validadas` }),
        barras(Object.entries(r.por_ruta || {}).map(([k, v]) => ({ etiqueta: k, valor: v.util / Math.max(1, v.util + v.no_util), ...v, serie: 1 })),
          { titulo: "Tasa útil por ruta", encabezado: "Ruta", columnaValor: "Tasa útil", formato: porcentaje, maximo: 1,
            extras: [{ titulo: "Útil", texto: (f) => String(f.util) }, { titulo: "No útil", texto: (f) => String(f.no_util) }] }),
        barras(Object.entries(r.por_modelo || {}).map(([k, v]) => ({ etiqueta: k, valor: v.util / Math.max(1, v.util + v.no_util), ...v, serie: 1 })),
          { titulo: "Tasa útil por modelo", encabezado: "Modelo", columnaValor: "Tasa útil", formato: porcentaje, maximo: 1,
            extras: [{ titulo: "Útil", texto: (f) => String(f.util) }, { titulo: "No útil", texto: (f) => String(f.no_util) }] }),
        barras(Object.entries(r.campos_corregidos || {}).map(([k, v]) => ({ etiqueta: k, valor: v, serie: 2 })),
          { titulo: "Campos corregidos por el archivista", encabezado: "Campo", columnaValor: "Correcciones" })),
      tarjeta("Latencia por endpoint",
        barras(Object.entries(m.latencia_por_endpoint || {}).map(([k, v]) => ({ etiqueta: k, valor: v.p50_ms || 0, p95: v.p95_ms, n: v.n })),
          { titulo: "p50 y p95 por endpoint", encabezado: "Endpoint", columnaValor: "p50", formato: ms,
            extras: [{ titulo: "p95", texto: (f) => ms(f.p95) }, { titulo: "Peticiones", texto: (f) => String(f.n) }] })),
      tarjeta("Configuración activa", el("dl", { clase: "interpretada" },
        el("dt", { texto: "Versión de configuración" }), el("dd", { texto: conf.version_configuracion }),
        ...Object.entries(conf.modelos || {}).flatMap(([k, v]) => [el("dt", { texto: `Modelo · ${k}` }), el("dd", { texto: v })]),
        el("dt", { texto: "Versiones de prompts" }), el("dd", { texto: Object.entries(conf.versiones_prompts || {}).map(([k, v]) => `${k} v${v}`).join(", ") || "—" }))));
    const texto = `Actualizado ${new Date(m.generado).toLocaleString("es-MX")} · ${m.eventos_considerados} eventos`;
    mensaje(estado, texto, "ok");
    anunciar("Métricas actualizadas");
  } catch (e) {
    mensaje(estado, e.message);
  } finally {
    panel.removeAttribute("aria-busy");
  }
}

document.getElementById("periodo").addEventListener("submit", (ev) => { ev.preventDefault(); cargar(); });
cargar();
