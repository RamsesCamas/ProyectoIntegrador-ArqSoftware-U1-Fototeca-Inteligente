// Métricas (v4 «Mesa de luz»): un documento de consulta, no un tablero. GET /api/metricas y GET /api/configuracion.
// En el encabezado, el estado («Actualizado …»), el periodo y «Actualizar»; debajo, las anclas de las secciones, las
// cifras clave en prosa y el panel: secciones (.panel = h2 en rótulo con filete arriba) con filas de catálogo y
// gráficas de barras neutras de comun.js, cada una con su tabla equivalente. Las barras no llevan `serie` ni `clave`:
// el estado se dice con texto y símbolo, nunca solo con el color.
import { anunciar, api, el } from "./api.js";
import { barras, CAPAS, crearMensaje, duracion, mensaje, numero, ORDEN_CAPAS, porcentaje, segundos } from "./comun.js";

const GRAVEDAD = { bloqueada: 0, sanitizado: 1, marcada: 2 };
// Resultado de un guardrail: tono, símbolo y texto (el símbolo y el tono nunca van solos)
const RESULTADO = { bloqueada: ["error", "×", "bloqueada", "bloqueadas"], sanitizado: ["neutra", "", "sanitizada", "sanitizadas"],
  marcada: ["aviso", "!", "marcada", "marcadas"] };
const FLUJOS = { fichas: "Fichas", busquedas: "Búsquedas" };
const RUTAS = { rapida: "rápida", cache: "caché" };
const CAMPOS = { titular: "Titular", texto_alternativo: "Texto alternativo", descripcion: "Descripción",
  descripcion_extendida: "Descripción extendida", palabras_clave: "Palabras clave" };
const MODELOS = { vision: "Modelo de visión", composicion: "Modelo de composición", embedding: "Modelo de embedding",
  embedding_secundario: "Modelo de embedding secundario" };
const ms = (v) => segundos(v || 0);
const ordenCapa = (c) => (c === "total" ? 99 : ORDEN_CAPAS.includes(c) ? ORDEN_CAPAS.indexOf(c) : 50);
const suma = (xs) => xs.reduce((s, n) => s + (n || 0), 0);
const plural = (n, uno, varios) => `${numero(n)} ${n === 1 ? uno : varios}`;
// Cifra con su unidad: nunca se parte entre líneas («38.8 s», «100.0 %»)
const sinCorte = (t) => String(t).replace(/ /g, "\u00a0");
const dos = (n) => String(n).padStart(2, "0");
/** Fecha y hora locales en ISO de 24 h: «2026-11-14 04:42:17» (el mismo formato en Métricas y en Archivo). */
const fechaIso = (d) => `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())} ${dos(d.getHours())}:${dos(d.getMinutes())}:${dos(d.getSeconds())}`;
/** Cifra dentro de una frase (.cifra de base.css). */
const c = (v) => el("span", { clase: "cifra", texto: sinCorte(v) });

const estado = document.getElementById("estado");
const tablero = document.getElementById("panel");
const resumen = document.getElementById("cifras-clave");
const selector = document.getElementById("desde");
const botonActualizar = document.getElementById("actualizar");
let turno = 0;
let conDatos = false;

// El estado y el periodo viven en el encabezado de la página, a la derecha del h1
const acciones = document.getElementById("acciones-metricas");
document.querySelector(".encabezado-acciones")?.append(acciones);
acciones.hidden = false;

// ── Piezas ──
/** Sección del documento: el h2 es hijo directo de la sección (E2E: #panel section > h2); debajo, una nota opcional. */
function panel(id, titulo, nota, ...cuerpo) {
  return el("section", { clase: "panel seccion-metrica", id, "aria-labelledby": `${id}-titulo` },
    el("h2", { id: `${id}-titulo`, texto: titulo }),
    nota ? el("p", { clase: "panel-nota", texto: nota }) : null,
    ...cuerpo);
}

/** Figura de barras con etiquetas técnicas (ids, modelos, endpoints, eventos): en mono. */
function conEtiquetasMono(figura) {
  figura.classList.add("etiquetas-mono");
  return figura;
}

function vigencia(s) {
  if (!s) return "sin vigencia";
  if (s % 86400 === 0) return plural(s / 86400, "día", "días");
  if (s % 3600 === 0) return plural(s / 3600, "hora", "horas");
  return duracion(s);
}

function esqueletos() {
  const linea = (clase = "") => el("span", { clase: `esqueleto linea ${clase}`.trim() });
  resumen.replaceChildren(linea(), linea("corta"));
  tablero.replaceChildren(...Array.from({ length: 2 }, () => el("div", { clase: "panel seccion-cargando", "aria-hidden": "true" },
    linea("corta"), el("span", { clase: "esqueleto bloque" }), linea(), linea("corta"))));
}

// ── Cifras clave, en prosa ──
function cifrasClave(m) {
  const a = m.accesibilidad || {};
  const f = m.latencia_por_capa?.fichas?.total;
  const b = m.latencia_por_capa?.busquedas?.total;
  const espacios = Object.values(m.cache || {});
  const consultas = suma(espacios.map((x) => x.consultas));
  const aciertos = suma(espacios.map((x) => (x.aciertos_exactos || 0) + (x.aciertos_semanticos || 0)));
  const r = m.retroalimentacion || {};
  const bloqueos = suma(Object.values(m.bloqueos || {}));
  const activaciones = suma((m.guardrails || []).map((g) => g.n));
  return [
    c(porcentaje(a.porcentaje_alt_validado)), " de las ", c(numero(a.fotos ?? 0)), " fotos tienen texto alternativo validado. ",
    f?.n ? ["Una ficha tarda ", c(ms(f.p50_ms)), " en la mediana (p95 ", c(ms(f.p95_ms)), ")"] : "Todavía no hay fichas medidas",
    b?.n ? [" y una búsqueda ", c(ms(b.p50_ms)), " (p95 ", c(ms(b.p95_ms)), "). "] : ". ",
    consultas ? ["La caché acertó ", c(numero(aciertos)), " de ", c(numero(consultas)), " consultas (", c(porcentaje(aciertos / consultas)), "); "] : "",
    r.total ? [c(numero(r.util ?? 0)), " de ", c(numero(r.total)), " opiniones fueron útiles (", c(porcentaje(r.tasa_util)), "), y "] : "",
    "los guardrails bloquearon ", c(numero(bloqueos)), " de ", c(numero(activaciones)), " activaciones.",
  ];
}

// ── Secciones ──
/** Latencia por capa: el p50 de cada capa con su p95 y su n, en barras neutras. Sin barra apilada ni «Proporción»: cada
 *  capa es una distribución medida aparte (con otra n) y las medianas no se suman. */
function latenciaPorCapa(m) {
  const flujos = Object.entries(m.latencia_por_capa || {});
  const total = (f) => m.latencia_por_capa?.[f]?.total?.n || 0;
  const nota = flujos.length ? `Medida en ${plural(total("fichas"), "ficha", "fichas")} y ${plural(total("busquedas"), "búsqueda", "búsquedas")}. `
    + "Cada fila es una distribución aparte, con su propia n: las medianas de las capas no se suman y su suma no es el total." : null;
  const bloques = flujos.map(([flujo, etapas]) => {
    const nombre = FLUJOS[flujo] || flujo;
    const ordenadas = Object.entries(etapas).sort(([x], [y]) => ordenCapa(x) - ordenCapa(y));
    const t = etapas.total;
    const id = `flujo-${flujo}`;
    return el("section", { clase: "flujo", "aria-labelledby": id },
      el("h3", { id, texto: nombre }),
      el("p", { clase: "flujo-resumen" }, t?.n ? ["Total: p50 ", c(ms(t.p50_ms)), ", p95 ", c(ms(t.p95_ms)), ", n = ", c(numero(t.n))] : "Sin datos todavía."),
      barras(ordenadas.map(([k, v]) => ({ etiqueta: k === "total" ? `Total de la ${flujo === "busquedas" ? "búsqueda" : "ficha"}` : CAPAS[k] || k,
        valor: v.p50_ms || 0, p95: v.p95_ms, n: v.n })),
      { titulo: `${nombre}: p50 por capa, con su p95 y su n`, encabezado: "Capa", columnaValor: "p50", formato: ms,
        extras: [{ titulo: "p95", texto: (f) => ms(f.p95) }, { titulo: "n", texto: (f) => numero(f.n) }] }));
  });
  const eventos = Object.entries(m.latencia_por_evento || {}).flatMap(([capa, evs]) =>
    Object.entries(evs).map(([evento, v]) => ({ etiqueta: `${capa} ${evento}`, valor: v.p50_ms || 0, p95: v.p95_ms, n: v.n })));
  return panel("sec-latencia", "Latencia por capa", nota,
    bloques.length ? el("div", { clase: "latencias" }, bloques) : el("p", { clase: "suave", texto: "Sin fichas ni búsquedas todavía." }),
    el("section", { clase: "por-evento", "aria-labelledby": "titulo-por-evento" },
      el("h3", { id: "titulo-por-evento", texto: "Por capa de la arquitectura y evento" }),
      conEtiquetasMono(barras(eventos, { titulo: "p50 por capa (C1–C7, T1, T2) y evento, con su p95 y su n", encabezado: "Capa y evento",
        columnaValor: "p50", formato: ms, extras: [{ titulo: "p95", texto: (f) => ms(f.p95) }, { titulo: "n", texto: (f) => numero(f.n) }] }))));
}

function cache(m, conf) {
  const espacios = Object.entries(m.cache || {});
  const consultas = suma(espacios.map(([, v]) => v.consultas));
  const parametros = conf?.parametros?.cache || {};
  const umbrales = [["fichas", "τ_dup", parametros.fichas], ["busquedas", "τ_busq", parametros.busquedas]].filter(([, , v]) => v);
  return panel("sec-cache", "Caché", espacios.length ? `${plural(consultas, "consulta", "consultas")} en dos espacios.` : null,
    barras(espacios.map(([k, v]) => ({ etiqueta: FLUJOS[k] || k, valor: v.tasa_aciertos || 0, consultas: v.consultas,
      aciertos_exactos: v.aciertos_exactos, aciertos_semanticos: v.aciertos_semanticos })),
    { titulo: "Tasa de aciertos por espacio", encabezado: "Espacio", columnaValor: "Tasa", formato: porcentaje, maximo: 1,
      extras: [{ titulo: "Consultas", texto: (f) => numero(f.consultas) }, { titulo: "Exactos", texto: (f) => numero(f.aciertos_exactos) },
        { titulo: "Semánticos", texto: (f) => numero(f.aciertos_semanticos) }] }),
    umbrales.length ? el("p", { clase: "nota-prosa" }, "Un acierto semántico reutiliza la respuesta de una consulta parecida, cuya similitud llega al umbral: ",
      umbrales.flatMap(([k, nombre, v], i) => [i ? "; " : "", `${(FLUJOS[k] || k).toLowerCase()}, `,
        el("span", { clase: "cifra", texto: `${nombre} ≥ ${v.tau_dup ?? v.tau_busq ?? "—"}` }), ` con vigencia de ${vigencia(v.ttl_s)}`]), ".") : null);
}

function accesibilidad(m) {
  const a = m.accesibilidad || {};
  return panel("sec-accesibilidad", "Accesibilidad del archivo", null,
    el("p", { clase: "nota-prosa" }, c(porcentaje(a.porcentaje_alt_validado)), " de las ", c(numero(a.fotos ?? 0)),
      " fotos tienen texto alternativo validado; hay ", c(numero(a.fichas_validadas ?? 0)), " fichas validadas, ",
      c(porcentaje(a.porcentaje_requiere_revision)), " requieren revisión y ", c(porcentaje(a.porcentaje_sin_ficha)), " no tienen ficha."),
    barras([{ etiqueta: "Texto alternativo validado", valor: a.alt_validado || 0 }, { etiqueta: "Borrador", valor: a.borrador || 0 },
      { etiqueta: "Requiere revisión", valor: a.requiere_revision || 0 }, { etiqueta: "Sin ficha", valor: a.sin_ficha || 0 }],
    { titulo: "Fotos por estado de su ficha", maximo: a.fotos || 1, encabezado: "Estado", columnaValor: "Fotos" }));
}

/** Figura de un resultado de guardrail: la leyenda dice el resultado en texto, con símbolo, y su total. */
function figuraResultado(res, filas) {
  const [tono, simbolo, uno, varios] = RESULTADO[res] || ["neutra", "", res, res];
  const figura = conEtiquetasMono(barras(filas.map((g) => ({ etiqueta: g.verificacion, valor: g.n })),
    { titulo: varios, encabezado: "Verificación", columnaValor: "Activaciones" }));
  figura.classList.add("figura-resultado");
  figura.querySelector("figcaption")?.replaceChildren(
    el("span", { clase: `resultado resultado-${tono}` }, simbolo ? el("span", { clase: "resultado-simbolo", "aria-hidden": "true", texto: simbolo }) : null,
      plural(suma(filas.map((g) => g.n)), uno, varios)),
    ` en ${plural(filas.length, "verificación", "verificaciones")}`);
  return figura;
}

function guardrails(m) {
  const lista = m.guardrails || [];
  const intervenciones = Object.keys(GRAVEDAD).map((res) => [res, lista.filter((g) => g.resultado === res).sort((x, y) => y.n - x.n)])
    .filter(([, filas]) => filas.length);
  const aprobadas = lista.filter((g) => g.resultado === "aprobada").sort((x, y) => y.n - x.n);
  return panel("sec-guardrails", "Guardrails", lista.length ? `${plural(suma(lista.map((g) => g.n)), "activación", "activaciones")} de las verificaciones de entrada y de salida.` : null,
    intervenciones.map(([res, filas]) => figuraResultado(res, filas)),
    aprobadas.length ? el("details", { clase: "plegable" },
      el("summary", {}, "Aprobadas: ", c(numero(suma(aprobadas.map((g) => g.n)))), ` en ${plural(aprobadas.length, "verificación", "verificaciones")}`),
      conEtiquetasMono(barras(aprobadas.map((g) => ({ etiqueta: g.verificacion, valor: g.n })),
        { titulo: "Aprobadas por verificación", encabezado: "Verificación", columnaValor: "Activaciones" }))) : null);
}

function enrutador(m) {
  const rutas = Object.entries(m.rutas || {});
  const nombreRuta = (k) => { const [flujo, ruta] = k.split(":"); return `${FLUJOS[flujo] || flujo}, ruta ${RUTAS[ruta] || ruta}`; };
  return panel("sec-enrutador", "Enrutador y agente", rutas.length ? `${plural(suma(rutas.map(([, v]) => v)), "decisión", "decisiones")} del enrutador.` : null,
    barras(rutas.map(([k, v]) => ({ etiqueta: nombreRuta(k), valor: v })),
      { titulo: "Rutas elegidas por el enrutador", encabezado: "Flujo y ruta", columnaValor: "Veces" }),
    barras(Object.entries(m.iteraciones_agente || {}).map(([k, v]) => ({ etiqueta: `${k} ${k === "1" ? "iteración" : "iteraciones"}`, valor: v })),
      { titulo: "Iteraciones del ciclo de agente por ficha", encabezado: "Iteraciones", columnaValor: "Fichas" }),
    barras(Object.entries(m.iteraciones_agente_busquedas || {}).map(([k, v]) => ({ etiqueta: `${k} ${k === "1" ? "reformulación" : "reformulaciones"}`, valor: v })),
      { titulo: "Reformulaciones por búsqueda", encabezado: "Reformulaciones", columnaValor: "Búsquedas" }));
}

function retroalimentacion(m) {
  const r = m.retroalimentacion || {};
  const tasa = (v) => v.util / Math.max(1, v.util + v.no_util);
  const extras = [{ titulo: "Útil", texto: (f) => numero(f.util) }, { titulo: "No útil", texto: (f) => numero(f.no_util) }];
  return panel("sec-retroalimentacion", "Retroalimentación", null,
    el("p", { clase: "nota-prosa" }, c(numero(r.total ?? 0)), " opiniones: ", c(numero(r.util ?? 0)), " útiles y ", c(numero(r.no_util ?? 0)),
      " no útiles (tasa útil ", c(porcentaje(r.tasa_util)), "); ", c(numero(r.con_comentario ?? 0)), " con comentario y ",
      c(numero(r.fichas_validadas ?? 0)), " fichas validadas."),
    barras(Object.entries(r.por_ruta || {}).map(([k, v]) => ({ etiqueta: `Ruta ${RUTAS[k] || k}`, valor: tasa(v), util: v.util, no_util: v.no_util })),
      { titulo: "Tasa útil por ruta", encabezado: "Ruta", columnaValor: "Tasa útil", formato: porcentaje, maximo: 1, extras }),
    conEtiquetasMono(barras(Object.entries(r.por_modelo || {}).map(([k, v]) => ({ etiqueta: k, valor: tasa(v), util: v.util, no_util: v.no_util })),
      { titulo: "Tasa útil por modelo", encabezado: "Modelo", columnaValor: "Tasa útil", formato: porcentaje, maximo: 1, extras })),
    barras(Object.entries(r.campos_corregidos || {}).map(([k, v]) => ({ etiqueta: CAMPOS[k] || k, valor: v })),
      { titulo: "Campos corregidos por el archivista", encabezado: "Campo", columnaValor: "Correcciones" }));
}

function usoPorModelo(m) {
  const modelos = Object.entries(m.modelos || {});
  return panel("sec-modelos", "Uso por modelo", modelos.length ? `${plural(suma(modelos.map(([, v]) => v.llamadas)), "llamada", "llamadas")} a los modelos locales.` : null,
    conEtiquetasMono(barras(modelos.map(([k, v]) => ({ etiqueta: k, valor: v.llamadas, ...v })),
      { titulo: "Llamadas por modelo", encabezado: "Modelo", columnaValor: "Llamadas",
        extras: [{ titulo: "Tokens de entrada", texto: (f) => numero(f.tokens_prompt) }, { titulo: "Tokens de salida", texto: (f) => numero(f.tokens_salida) },
          { titulo: "Tiempo total", texto: (f) => duracion((f.tiempo_ms || 0) / 1000) }, { titulo: "Respaldos", texto: (f) => numero(f.respaldos) },
          { titulo: "Tiempos agotados", texto: (f) => numero(f.tiempos_agotados) }, { titulo: "JSON inválido", texto: (f) => numero(f.json_invalido) }] })));
}

function configuracion(conf) {
  const dato = (k, v) => [el("dt", { texto: k }), el("dd", { clase: "mono", texto: v ?? "—" })];
  return panel("sec-configuracion", "Configuración activa", null,
    el("dl", { clase: "configuracion" },
      dato("Versión de configuración", conf.version_configuracion),
      dato("Versión del servicio", conf.version_servicio),
      dato("Versión del corpus", conf.version_corpus),
      ...Object.entries(conf.modelos || {}).flatMap(([k, v]) => dato(MODELOS[k] || `Modelo ${k}`, v)),
      el("dt", { texto: "Versiones de los prompts" }),
      el("dd", {}, Object.keys(conf.versiones_prompts || {}).length
        ? el("ul", { clase: "lista-simple" }, Object.entries(conf.versiones_prompts).map(([k, v]) => el("li", { texto: `${k}: ${v}` })))
        : "—")));
}

function latenciaPorEndpoint(m) {
  const endpoints = Object.entries(m.latencia_por_endpoint || {}).sort(([, x], [, y]) => (y.p50_ms || 0) - (x.p50_ms || 0));
  return panel("sec-endpoints", "Latencia por endpoint", endpoints.length ? `${plural(suma(endpoints.map(([, v]) => v.n)), "petición", "peticiones")}, del endpoint más lento al más rápido.` : null,
    conEtiquetasMono(barras(endpoints.map(([k, v]) => ({ etiqueta: k, valor: v.p50_ms || 0, p95: v.p95_ms, n: v.n })),
      { titulo: "p50 por endpoint, con su p95", encabezado: "Endpoint", columnaValor: "p50", formato: ms,
        extras: [{ titulo: "p95", texto: (f) => ms(f.p95) }, { titulo: "Peticiones", texto: (f) => numero(f.n) }] })));
}

function errorDeCarga(texto) {
  return el("section", { clase: "panel error-carga", "aria-labelledby": "titulo-error-carga" },
    el("h2", { id: "titulo-error-carga", texto: "No se pudieron leer las métricas" }),
    el("p", { texto }),
    el("button", { type: "button", clase: "boton", onclick: () => cargar() }, "Reintentar"));
}

// ── Carga ──
async function cargar() {
  const mio = ++turno;
  const horas = selector.value;
  const desde = horas ? new Date(Date.now() - Number(horas) * 3600 * 1000).toISOString() : "";
  tablero.setAttribute("aria-busy", "true");
  botonActualizar.setAttribute("aria-busy", "true");
  if (!conDatos) esqueletos();
  mensaje(estado, conDatos ? "Actualizando…" : "Cargando las métricas…", "info");
  try {
    const [{ cuerpo: m }, conf] = await Promise.all([
      api(`/metricas${desde ? `?desde=${encodeURIComponent(desde)}` : ""}`),
      api("/configuracion").then((r) => r.cuerpo).catch(() => null)]);
    if (mio !== turno) return;
    resumen.replaceChildren(...cifrasClave(m).flat(2));
    const vacio = !m.eventos_considerados;
    tablero.replaceChildren(...[
      vacio ? crearMensaje("No hay eventos en este periodo: las secciones muestran solo el estado del archivo. Elige «Todo el historial» para ver todo.", "info") : null,
      latenciaPorCapa(m), cache(m, conf), accesibilidad(m), guardrails(m), enrutador(m), retroalimentacion(m), usoPorModelo(m),
      conf ? configuracion(conf) : null, latenciaPorEndpoint(m)].filter(Boolean));
    conDatos = true;
    const generado = m.generado ? new Date(m.generado) : new Date();
    mensaje(estado, el("span", {}, "Actualizado ", el("time", { clase: "mono", datetime: generado.toISOString(), texto: fechaIso(generado) }),
      `, ${plural(m.eventos_considerados ?? 0, "evento", "eventos")}`), "ok");
    anunciar("Métricas actualizadas");
  } catch (e) {
    if (mio !== turno) return;
    // Sin datos previos, el panel explica el error con «Reintentar»: en el encabezado basta una línea corta
    mensaje(estado, conDatos ? `No se pudo actualizar: ${e.message}` : "No se pudieron leer las métricas.");
    if (!conDatos) {
      resumen.replaceChildren();
      tablero.replaceChildren(errorDeCarga(e.message));
    }
  } finally {
    if (mio === turno) {
      tablero.removeAttribute("aria-busy");
      botonActualizar.removeAttribute("aria-busy");
    }
  }
}

document.getElementById("periodo").addEventListener("submit", (ev) => { ev.preventDefault(); cargar(); });
selector.addEventListener("change", () => cargar());
cargar();
