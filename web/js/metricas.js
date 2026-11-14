// Métricas: GET /api/metricas y GET /api/configuracion. Cifras clave arriba y el panel en dos columnas; gráficas SVG
// propias, cada una con su tabla equivalente. El color de cada serie va por clave de capa (comun.js · SERIE_CAPA).
import { anunciar, api, el } from "./api.js";
import { barraApilada, barras, CAPAS, duracion, mensaje, numero, ORDEN_CAPAS, porcentaje, segundos } from "./comun.js";

// Rojo (serie 5) solo para «bloqueada»
const SERIE_RESULTADO = { aprobada: 2, sanitizado: 6, marcada: 3, bloqueada: 5 };
const FLUJOS = { fichas: "Fichas", busquedas: "Búsquedas" };
const ms = (v) => segundos(v || 0);
const ordenCapa = (c) => (c === "total" ? 99 : ORDEN_CAPAS.includes(c) ? ORDEN_CAPAS.indexOf(c) : 50);

function tarjeta(titulo, ...hijos) {
  return el("section", { clase: "tarjeta" }, el("h2", { texto: titulo }), ...hijos);
}

function ancha(seccion) {
  seccion.classList.add("ancha");
  return seccion;
}

function cifrasClave(m) {
  const a = m.accesibilidad || {};
  const f = m.latencia_por_capa?.fichas?.total;
  const b = m.latencia_por_capa?.busquedas?.total;
  const espacios = Object.values(m.cache || {});
  const consultas = espacios.reduce((s, c) => s + (c.consultas || 0), 0);
  const aciertos = espacios.reduce((s, c) => s + (c.aciertos_exactos || 0) + (c.aciertos_semanticos || 0), 0);
  const r = m.retroalimentacion || {};
  const bloqueos = Object.values(m.bloqueos || {}).reduce((s, n) => s + (n || 0), 0);
  return [
    [porcentaje(a.porcentaje_alt_validado), `de ${numero(a.fotos ?? 0)} fotos tienen texto alternativo validado`],
    [f?.n ? ms(f.p50_ms) : "—", f?.n ? `por ficha (p50) · p95 ${ms(f.p95_ms)}` : "por ficha (p50) · sin datos"],
    [b?.n ? ms(b.p50_ms) : "—", b?.n ? `por búsqueda (p50) · p95 ${ms(b.p95_ms)}` : "por búsqueda (p50) · sin datos"],
    [consultas ? porcentaje(aciertos / consultas) : "—", `aciertos de caché (${numero(aciertos)} de ${numero(consultas)} consultas)`],
    [porcentaje(r.tasa_util), `opiniones útiles (de ${numero(r.total ?? 0)})`],
    [numero(bloqueos), "bloqueos de los guardrails"],
  ].map(([valor, texto]) => el("article", { clase: "tarjeta" }, el("p", { clase: "cifra", texto: valor }), el("p", { clase: "cifra-etiqueta", texto })));
}

function latenciaPorEtapa(m) {
  const flujos = Object.entries(m.latencia_por_capa || {});
  if (!flujos.length) return [el("p", { clase: "suave", texto: "Sin fichas ni búsquedas todavía." })];
  return [el("div", { clase: "latencias" }, flujos.map(([flujo, etapas]) => {
    const ordenadas = Object.entries(etapas).sort(([x], [y]) => ordenCapa(x) - ordenCapa(y));
    const partes = ordenadas.filter(([c, v]) => c !== "total" && v.n && v.p50_ms > 0)
      .map(([c, v]) => ({ clave: c, etiqueta: CAPAS[c] || c, valor: v.p50_ms }));
    const total = etapas.total;
    const nombre = FLUJOS[flujo] || flujo;
    return el("div", {},
      el("h3", { texto: `${nombre}${total?.n ? ` · total p50 ${ms(total.p50_ms)}, p95 ${ms(total.p95_ms)} (n=${numero(total.n)})` : ""}` }),
      partes.length ? barraApilada(partes, { titulo: `${nombre}: tiempo p50 por capa (barras apiladas)` }) : null,
      barras(ordenadas.map(([c, v]) => ({ clave: c, etiqueta: CAPAS[c] || c, valor: v.p95_ms || 0, n: v.n, p50: v.p50_ms })),
        { titulo: `${nombre}: p50 y p95 por capa`, encabezado: "Capa", columnaValor: "p95", formato: ms,
          extras: [{ titulo: "p50", texto: (f) => ms(f.p50) }, { titulo: "n", texto: (f) => numero(f.n) }] }));
  }))];
}

function latenciaPorCapaArquitectura(m) {
  const filas = Object.entries(m.latencia_por_evento || {}).flatMap(([capa, eventos]) =>
    Object.entries(eventos).map(([evento, v]) => ({ etiqueta: `${capa} · ${evento}`, valor: v.p50_ms || 0, p95: v.p95_ms, n: v.n })));
  return barras(filas, { titulo: "p50 y p95 por capa (C1–C7, T1, T2) y evento", encabezado: "Capa · evento", columnaValor: "p50",
    formato: ms, extras: [{ titulo: "p95", texto: (f) => ms(f.p95) }, { titulo: "n", texto: (f) => numero(f.n) }] });
}

async function cargar() {
  const horas = document.getElementById("desde").value;
  const desde = horas ? new Date(Date.now() - Number(horas) * 3600 * 1000).toISOString() : "";
  const estado = document.getElementById("estado");
  const panel = document.getElementById("panel");
  const cifras = document.getElementById("cifras-clave");
  panel.setAttribute("aria-busy", "true");
  try {
    const [{ cuerpo: m }, { cuerpo: conf }] = await Promise.all([
      api(`/metricas${desde ? `?desde=${encodeURIComponent(desde)}` : ""}`), api("/configuracion")]);
    const a = m.accesibilidad || {};
    const r = m.retroalimentacion || {};
    const guardrails = [...(m.guardrails || [])].sort((x, y) => y.n - x.n);
    cifras.replaceChildren(...cifrasClave(m));
    panel.replaceChildren(
      ancha(tarjeta("Latencia por capa", ...latenciaPorEtapa(m), latenciaPorCapaArquitectura(m))),
      tarjeta("Accesibilidad del archivo",
        el("p", { clase: "cifra", texto: porcentaje(a.porcentaje_alt_validado) }),
        el("p", { texto: `de ${numero(a.fotos ?? 0)} fotos tienen texto alternativo validado · ${numero(a.fichas_validadas ?? 0)} fichas validadas · `
          + `${porcentaje(a.porcentaje_requiere_revision)} requieren revisión · ${porcentaje(a.porcentaje_sin_ficha)} sin ficha` }),
        barras([{ etiqueta: "Texto alternativo validado", valor: a.alt_validado || 0, serie: 2 },
          { etiqueta: "Borrador", valor: a.borrador || 0, serie: 7 },
          { etiqueta: "Requiere revisión", valor: a.requiere_revision || 0, serie: 3 },
          { etiqueta: "Sin ficha", valor: a.sin_ficha || 0, serie: 1 }],
        { titulo: "Fotos por estado de su ficha", maximo: a.fotos || 1, encabezado: "Estado", columnaValor: "Fotos" })),
      tarjeta("Caché",
        barras(Object.entries(m.cache || {}).map(([k, v]) => ({ etiqueta: FLUJOS[k] || k, valor: v.tasa_aciertos || 0, clave: "cache", ...v })),
          { titulo: "Tasa de aciertos por espacio", encabezado: "Espacio", columnaValor: "Tasa", formato: porcentaje, maximo: 1,
            extras: [{ titulo: "Consultas", texto: (f) => numero(f.consultas) }, { titulo: "Exactos", texto: (f) => numero(f.aciertos_exactos) },
              { titulo: "Semánticos", texto: (f) => numero(f.aciertos_semanticos) }] })),
      tarjeta("Enrutador y agente",
        barras(Object.entries(m.rutas || {}).map(([k, v]) => {
          const [flujo, ruta] = k.split(":");
          return { etiqueta: `${FLUJOS[flujo] || flujo} · ${ruta}`, valor: v, clave: "enrutador" };
        }), { titulo: "Rutas elegidas", encabezado: "Flujo · ruta", columnaValor: "Veces" }),
        barras(Object.entries(m.iteraciones_agente || {}).map(([k, v]) => ({ etiqueta: `${k} iteraciones`, valor: v })),
          { titulo: "Iteraciones del ciclo de agente por ficha", encabezado: "Iteraciones", columnaValor: "Fichas" }),
        barras(Object.entries(m.iteraciones_agente_busquedas || {}).map(([k, v]) => ({ etiqueta: `${k} reformulaciones`, valor: v })),
          { titulo: "Reformulaciones por búsqueda", encabezado: "Reformulaciones", columnaValor: "Búsquedas" })),
      tarjeta("Retroalimentación",
        el("p", { texto: `${numero(r.total ?? 0)} opiniones · ${numero(r.util ?? 0)} útiles · ${numero(r.no_util ?? 0)} no útiles · tasa útil ${porcentaje(r.tasa_util)} · `
          + `${numero(r.con_comentario ?? 0)} con comentario · ${numero(r.fichas_validadas ?? 0)} fichas validadas` }),
        barras(Object.entries(r.por_ruta || {}).map(([k, v]) => ({ etiqueta: k, valor: v.util / Math.max(1, v.util + v.no_util), ...v, serie: 2 })),
          { titulo: "Tasa útil por ruta", encabezado: "Ruta", columnaValor: "Tasa útil", formato: porcentaje, maximo: 1,
            extras: [{ titulo: "Útil", texto: (f) => numero(f.util) }, { titulo: "No útil", texto: (f) => numero(f.no_util) }] }),
        barras(Object.entries(r.por_modelo || {}).map(([k, v]) => ({ etiqueta: k, valor: v.util / Math.max(1, v.util + v.no_util), ...v, serie: 2 })),
          { titulo: "Tasa útil por modelo", encabezado: "Modelo", columnaValor: "Tasa útil", formato: porcentaje, maximo: 1,
            extras: [{ titulo: "Útil", texto: (f) => numero(f.util) }, { titulo: "No útil", texto: (f) => numero(f.no_util) }] }),
        barras(Object.entries(r.campos_corregidos || {}).map(([k, v]) => ({ etiqueta: k, valor: v, serie: 3 })),
          { titulo: "Campos corregidos por el archivista", encabezado: "Campo", columnaValor: "Correcciones" })),
      tarjeta("Guardrails",
        barras(guardrails.map((g) => ({ etiqueta: `${g.verificacion} · ${g.resultado}`, valor: g.n, serie: SERIE_RESULTADO[g.resultado] ?? 7 })),
          { titulo: "Activaciones por verificación y resultado", encabezado: "Verificación · resultado", columnaValor: "Activaciones" })),
      ancha(tarjeta("Uso por modelo",
        barras(Object.entries(m.modelos || {}).map(([k, v]) => ({ etiqueta: k, valor: v.llamadas, ...v })),
          { titulo: "Llamadas por modelo", encabezado: "Modelo", columnaValor: "Llamadas",
            extras: [{ titulo: "Tokens de entrada", texto: (f) => numero(f.tokens_prompt) }, { titulo: "Tokens de salida", texto: (f) => numero(f.tokens_salida) },
              { titulo: "Tiempo total", texto: (f) => duracion((f.tiempo_ms || 0) / 1000) }, { titulo: "Respaldos", texto: (f) => numero(f.respaldos) },
              { titulo: "Tiempos agotados", texto: (f) => numero(f.tiempos_agotados) }, { titulo: "JSON inválido", texto: (f) => numero(f.json_invalido) }] }))),
      tarjeta("Latencia por endpoint",
        barras(Object.entries(m.latencia_por_endpoint || {}).map(([k, v]) => ({ etiqueta: k, valor: v.p50_ms || 0, p95: v.p95_ms, n: v.n })),
          { titulo: "p50 y p95 por endpoint", encabezado: "Endpoint", columnaValor: "p50", formato: ms,
            extras: [{ titulo: "p95", texto: (f) => ms(f.p95) }, { titulo: "Peticiones", texto: (f) => numero(f.n) }] })),
      tarjeta("Configuración activa", el("dl", { clase: "interpretada apilada" },
        el("dt", { texto: "Versión de configuración" }), el("dd", { texto: conf.version_configuracion }),
        ...Object.entries(conf.modelos || {}).flatMap(([k, v]) => [el("dt", { texto: `Modelo · ${k}` }), el("dd", { texto: v })]),
        el("dt", { texto: "Versiones de prompts" }),
        el("dd", {}, Object.keys(conf.versiones_prompts || {}).length
          ? el("ul", { clase: "lista-simple" }, Object.entries(conf.versiones_prompts).map(([k, v]) => el("li", { texto: `${k}: ${v}` })))
          : "—"))));
    const texto = `Actualizado ${new Date(m.generado).toLocaleString("es-MX")} · ${numero(m.eventos_considerados)} eventos`;
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
