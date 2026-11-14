// Métricas: GET /api/metricas y GET /api/configuracion. En el encabezado, el estado («Actualizado …»), el periodo y
// «Actualizar»; debajo, la barra de anclas (fija al desplazarse), la banda de 6 cifras clave y el panel: secciones con
// icono en su cabecera, a todo el ancho las de tablas anchas y en dos columnas equilibradas las demás.
// Gráficas SVG de comun.js, cada una con su tabla equivalente. Las barras de un solo valor van neutras (sin `serie` ni
// `clave`): el estado se dice con texto e icono (insignias), nunca solo con el color de la barra.
import { anunciar, api, el } from "./api.js";
import { barras, CAPAS, crearMensaje, duracion, mensaje, numero, ORDEN_CAPAS, porcentaje, segundos } from "./comun.js";
import { icono } from "./iconos.js";

const GRAVEDAD = { bloqueada: 0, sanitizado: 1, marcada: 2 };
// Resultado de un guardrail: variante de insignia, icono y texto (el color nunca va solo)
const RESULTADO = { bloqueada: ["error", "error", "bloqueada"], sanitizado: ["neutra", "escudo-check", "sanitizada"],
  marcada: ["aviso", "alerta", "marcada"], aprobada: ["ok", "check", "aprobada"] };
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

const estado = document.getElementById("estado");
const tablero = document.getElementById("panel");
const banda = document.getElementById("cifras-clave");
const selector = document.getElementById("desde");
const botonActualizar = document.getElementById("actualizar");
let turno = 0;
let conDatos = false;

// El estado y el periodo viven en el encabezado de la página, a la derecha del h1
const acciones = document.getElementById("acciones-metricas");
document.querySelector(".encabezado-acciones")?.append(acciones);
acciones.hidden = false;

// ── Piezas ──
/** Panel con su cabecera: el h2 (con icono) es hijo directo de la sección; el texto auxiliar va en la misma franja. */
function panel(id, titulo, nombreIcono, auxiliar, ...cuerpo) {
  return el("section", { clase: `panel panel-metrica${auxiliar ? " con-auxiliar" : ""}`, id, "aria-labelledby": `${id}-titulo` },
    el("h2", { id: `${id}-titulo` }, icono(nombreIcono), titulo),
    auxiliar ? el("p", { clase: "panel-auxiliar", texto: auxiliar }) : null,
    el("div", { clase: "panel-cuerpo" }, ...cuerpo));
}

function cifra(nombreIcono, valor, etiqueta, sub) {
  return el("article", { clase: "cifra" }, icono(nombreIcono),
    el("p", { clase: "cifra-valor", texto: sinCorte(valor) }),
    el("p", { clase: "cifra-etiqueta", texto: etiqueta }),
    el("p", { clase: "cifra-sub", texto: sub }));
}

/** Datos en línea: [[valor, texto], …] → «37 útiles · 28 no útiles · …» con el valor resaltado (en mono). */
function datosEnLinea(pares) {
  return el("ul", { clase: "datos-linea" }, pares.map(([v, t]) => el("li", {}, el("strong", { texto: sinCorte(v) }), ` ${t}`)));
}

/** Figura de barras con etiquetas técnicas (ids, modelos, rutas, eventos): en mono. */
function conEtiquetasMono(figura) {
  figura.classList.add("etiquetas-mono");
  return figura;
}

/** Figura de barras de un resultado de guardrail: la leyenda es su insignia (icono y texto) con el total. */
function figuraResultado(res, filas, [uno, varios]) {
  const figura = conEtiquetasMono(barras(filas.map((g) => ({ etiqueta: g.verificacion, valor: g.n })),
    { titulo: varios, encabezado: "Verificación", columnaValor: "Activaciones" }));
  figura.classList.add("figura-resultado");
  const [clase, nombreIcono] = RESULTADO[res] || ["neutra", "info"];
  figura.querySelector("figcaption")?.replaceChildren(
    el("span", { clase: `insignia ${clase}` }, icono(nombreIcono), plural(suma(filas.map((g) => g.n)), uno, varios)),
    el("span", { clase: "suave", texto: `en ${plural(filas.length, "verificación", "verificaciones")}` }));
  return figura;
}

function vigencia(s) {
  if (!s) return "—";
  if (s % 86400 === 0) return plural(s / 86400, "día", "días");
  if (s % 3600 === 0) return plural(s / 3600, "hora", "horas");
  return duracion(s);
}

function esqueletos() {
  const linea = (clase = "") => el("span", { clase: `esqueleto linea ${clase}`.trim() });
  banda.replaceChildren(...Array.from({ length: 6 }, () => el("div", { clase: "cifra cifra-cargando", "aria-hidden": "true" },
    el("span", { clase: "esqueleto icono-esqueleto" }), el("span", { clase: "esqueleto valor-esqueleto" }), linea(), linea("corta"))));
  const bloque = (alto) => el("div", { clase: "panel panel-cargando", "aria-hidden": "true" },
    el("div", { clase: "panel-cargando-cabecera" }, linea("corta")),
    el("div", { clase: "panel-cuerpo" }, el("span", { clase: `esqueleto bloque ${alto}` }), linea(), linea("corta")));
  tablero.replaceChildren(bloque("alto"), el("div", { clase: "reticula" },
    el("div", { clase: "col-6" }, bloque("")), el("div", { clase: "col-6" }, bloque(""))));
}

// ── Cifras clave ──
function cifrasClave(m) {
  const a = m.accesibilidad || {};
  const f = m.latencia_por_capa?.fichas?.total;
  const b = m.latencia_por_capa?.busquedas?.total;
  const espacios = Object.values(m.cache || {});
  const consultas = suma(espacios.map((c) => c.consultas));
  const aciertos = suma(espacios.map((c) => (c.aciertos_exactos || 0) + (c.aciertos_semanticos || 0)));
  const r = m.retroalimentacion || {};
  const bloqueos = suma(Object.values(m.bloqueos || {}));
  const activaciones = suma((m.guardrails || []).map((g) => g.n));
  return [
    cifra("ojo", porcentaje(a.porcentaje_alt_validado), "Texto alternativo validado", `${numero(a.alt_validado ?? 0)} de ${numero(a.fotos ?? 0)}`),
    cifra("catalogar", f?.n ? ms(f.p50_ms) : "—", "Por ficha (p50)", f?.n ? `p95 ${ms(f.p95_ms)}` : "sin fichas"),
    cifra("buscar", b?.n ? ms(b.p50_ms) : "—", "Por búsqueda (p50)", b?.n ? `p95 ${ms(b.p95_ms)}` : "sin búsquedas"),
    cifra("rayo", consultas ? porcentaje(aciertos / consultas) : "—", "Aciertos de caché", `${numero(aciertos)} de ${numero(consultas)}`),
    cifra("archivista", porcentaje(r.tasa_util), "Opiniones útiles", `${numero(r.util ?? 0)} de ${numero(r.total ?? 0)}`),
    cifra("escudo", numero(bloqueos), "Bloqueos de guardrails", `de ${numero(activaciones)}`),
  ];
}

// ── Secciones ──
/** Latencia por capa: el p50 de cada capa con su p95 y su n, en barras neutras. Sin barra apilada ni «Proporción»: cada
 *  capa es una distribución medida aparte (con otra n) y las medianas no se suman. */
function latenciaPorCapa(m) {
  const flujos = Object.entries(m.latencia_por_capa || {});
  const total = (f) => m.latencia_por_capa?.[f]?.total?.n || 0;
  const auxiliar = flujos.length ? `${plural(total("fichas"), "ficha", "fichas")} · ${plural(total("busquedas"), "búsqueda", "búsquedas")}` : null;
  const bloques = flujos.map(([flujo, etapas]) => {
    const nombre = FLUJOS[flujo] || flujo;
    const ordenadas = Object.entries(etapas).sort(([x], [y]) => ordenCapa(x) - ordenCapa(y));
    const t = etapas.total;
    const id = `flujo-${flujo}`;
    return el("section", { clase: "flujo", "aria-labelledby": id },
      el("h3", { id }, icono(flujo === "fichas" ? "catalogar" : flujo === "busquedas" ? "buscar" : "reloj"), nombre),
      el("p", { clase: "flujo-resumen", texto: t?.n ? [`total p50 ${ms(t.p50_ms)}`, `p95 ${ms(t.p95_ms)}`, `n = ${numero(t.n)}`].map(sinCorte).join(" · ")
        : "sin datos todavía" }),
      barras(ordenadas.map(([c, v]) => ({ etiqueta: c === "total" ? `Total de la ${flujo === "busquedas" ? "búsqueda" : "ficha"}` : CAPAS[c] || c,
        valor: v.p50_ms || 0, p95: v.p95_ms, n: v.n })),
      { titulo: `${nombre}: p50 por capa, con su p95 y su n`, encabezado: "Capa", columnaValor: "p50", formato: ms,
        extras: [{ titulo: "p95", texto: (f) => ms(f.p95) }, { titulo: "n", texto: (f) => numero(f.n) }] }));
  });
  const eventos = Object.entries(m.latencia_por_evento || {}).flatMap(([capa, evs]) =>
    Object.entries(evs).map(([evento, v]) => ({ etiqueta: `${capa} · ${evento}`, valor: v.p50_ms || 0, p95: v.p95_ms, n: v.n })));
  return panel("sec-latencia", "Latencia por capa", "reloj", auxiliar,
    bloques.length ? el("div", { clase: "latencias" }, bloques) : el("p", { clase: "suave", texto: "Sin fichas ni búsquedas todavía." }),
    el("p", { clase: "nota-percentiles" }, icono("info"),
      "Cada fila es una distribución medida aparte, con su propia n: las medianas de las capas no se suman y su suma no es el total."),
    el("section", { clase: "por-evento", "aria-labelledby": "titulo-por-evento" },
      el("h3", { id: "titulo-por-evento" }, icono("servidor"), "Por capa de la arquitectura y evento"),
      conEtiquetasMono(barras(eventos, { titulo: "p50 por capa (C1–C7, T1, T2) y evento, con su p95 y su n", encabezado: "Capa · evento",
        columnaValor: "p50", formato: ms, extras: [{ titulo: "p95", texto: (f) => ms(f.p95) }, { titulo: "n", texto: (f) => numero(f.n) }] }))));
}

function cache(m, conf) {
  const espacios = Object.entries(m.cache || {});
  const consultas = suma(espacios.map(([, v]) => v.consultas));
  const parametros = conf?.parametros?.cache || {};
  const umbral = { fichas: ["τ_dup", parametros.fichas?.tau_dup], busquedas: ["τ_busq", parametros.busquedas?.tau_busq] };
  const configurados = Object.entries(parametros).filter(([, v]) => v && typeof v === "object");
  return panel("sec-cache", "Caché", "rayo", espacios.length ? plural(consultas, "consulta", "consultas") : null,
    el("div", { clase: "cache-cuerpo" },
      barras(espacios.map(([k, v]) => ({ etiqueta: FLUJOS[k] || k, valor: v.tasa_aciertos || 0, consultas: v.consultas,
        aciertos_exactos: v.aciertos_exactos, aciertos_semanticos: v.aciertos_semanticos })),
      { titulo: "Tasa de aciertos por espacio", encabezado: "Espacio", columnaValor: "Tasa", formato: porcentaje, maximo: 1,
        extras: [{ titulo: "Consultas", texto: (f) => numero(f.consultas) }, { titulo: "Exactos", texto: (f) => numero(f.aciertos_exactos) },
          { titulo: "Semánticos", texto: (f) => numero(f.aciertos_semanticos) }] }),
      configurados.length ? el("aside", { clase: "umbrales", "aria-labelledby": "titulo-umbrales" },
        el("h3", { id: "titulo-umbrales", texto: "Umbrales y vigencia" }),
        el("p", { clase: "umbrales-nota", texto: "Un acierto semántico reutiliza la respuesta de una consulta parecida: su similitud llega al umbral τ." }),
        el("dl", {}, configurados.flatMap(([k, v]) => {
          const [nombre, valor] = umbral[k] || ["τ", null];
          return [el("dt", { texto: FLUJOS[k] || k }),
            el("dd", {}, el("span", { clase: "umbral", texto: valor !== null && valor !== undefined ? `${nombre} ≥ ${valor}` : "sin umbral" }),
              el("span", { clase: "vigencia", texto: `vigencia ${vigencia(v.ttl_s)}` }))];
        }))) : null));
}

function accesibilidad(m) {
  const a = m.accesibilidad || {};
  return panel("sec-accesibilidad", "Accesibilidad del archivo", "ojo", a.fotos !== undefined ? plural(a.fotos, "foto", "fotos") : null,
    el("div", { clase: "destacado" },
      el("p", { clase: "destacado-valor", texto: sinCorte(porcentaje(a.porcentaje_alt_validado)) }),
      el("p", { clase: "destacado-texto", texto: `de las ${numero(a.fotos ?? 0)} fotos tienen texto alternativo validado` })),
    datosEnLinea([[numero(a.fichas_validadas ?? 0), "fichas validadas"], [porcentaje(a.porcentaje_requiere_revision), "requieren revisión"],
      [porcentaje(a.porcentaje_sin_ficha), "sin ficha"]]),
    barras([{ etiqueta: "Texto alternativo validado", valor: a.alt_validado || 0 }, { etiqueta: "Borrador", valor: a.borrador || 0 },
      { etiqueta: "Requiere revisión", valor: a.requiere_revision || 0 }, { etiqueta: "Sin ficha", valor: a.sin_ficha || 0 }],
    { titulo: "Fotos por estado de su ficha", maximo: a.fotos || 1, encabezado: "Estado", columnaValor: "Fotos" }));
}

function enrutador(m) {
  const rutas = Object.entries(m.rutas || {});
  const nombreRuta = (k) => { const [flujo, ruta] = k.split(":"); return `${FLUJOS[flujo] || flujo} · ${RUTAS[ruta] || ruta}`; };
  return panel("sec-enrutador", "Enrutador y agente", "bifurcacion", rutas.length ? plural(suma(rutas.map(([, v]) => v)), "decisión", "decisiones") : null,
    barras(rutas.map(([k, v]) => ({ etiqueta: nombreRuta(k), valor: v })),
      { titulo: "Rutas elegidas por el enrutador", encabezado: "Flujo · ruta", columnaValor: "Veces" }),
    barras(Object.entries(m.iteraciones_agente || {}).map(([k, v]) => ({ etiqueta: `${k} ${k === "1" ? "iteración" : "iteraciones"}`, valor: v })),
      { titulo: "Iteraciones del ciclo de agente por ficha", encabezado: "Iteraciones", columnaValor: "Fichas" }),
    barras(Object.entries(m.iteraciones_agente_busquedas || {}).map(([k, v]) => ({ etiqueta: `${k} ${k === "1" ? "reformulación" : "reformulaciones"}`, valor: v })),
      { titulo: "Reformulaciones por búsqueda", encabezado: "Reformulaciones", columnaValor: "Búsquedas" }));
}

function retroalimentacion(m) {
  const r = m.retroalimentacion || {};
  const tasa = (v) => v.util / Math.max(1, v.util + v.no_util);
  const extras = [{ titulo: "Útil", texto: (f) => numero(f.util) }, { titulo: "No útil", texto: (f) => numero(f.no_util) }];
  return panel("sec-retroalimentacion", "Retroalimentación", "archivista", r.total !== undefined ? plural(r.total, "opinión", "opiniones") : null,
    datosEnLinea([[numero(r.util ?? 0), "útiles"], [numero(r.no_util ?? 0), "no útiles"], [porcentaje(r.tasa_util), "tasa útil"],
      [numero(r.con_comentario ?? 0), "con comentario"], [numero(r.fichas_validadas ?? 0), "fichas validadas"]]),
    barras(Object.entries(r.por_ruta || {}).map(([k, v]) => ({ etiqueta: RUTAS[k] || k, valor: tasa(v), util: v.util, no_util: v.no_util })),
      { titulo: "Tasa útil por ruta", encabezado: "Ruta", columnaValor: "Tasa útil", formato: porcentaje, maximo: 1, extras }),
    conEtiquetasMono(barras(Object.entries(r.por_modelo || {}).map(([k, v]) => ({ etiqueta: k, valor: tasa(v), util: v.util, no_util: v.no_util })),
      { titulo: "Tasa útil por modelo", encabezado: "Modelo", columnaValor: "Tasa útil", formato: porcentaje, maximo: 1, extras })),
    barras(Object.entries(r.campos_corregidos || {}).map(([k, v]) => ({ etiqueta: CAMPOS[k] || k, valor: v })),
      { titulo: "Campos corregidos por el archivista", encabezado: "Campo", columnaValor: "Correcciones" }));
}

function guardrails(m) {
  const lista = m.guardrails || [];
  const por = (res) => suma(lista.filter((g) => g.resultado === res).map((g) => g.n));
  const intervenciones = Object.keys(GRAVEDAD).map((res) => [res, lista.filter((g) => g.resultado === res).sort((x, y) => y.n - x.n)])
    .filter(([, filas]) => filas.length);
  const aprobadas = lista.filter((g) => g.resultado === "aprobada").sort((x, y) => y.n - x.n);
  return panel("sec-guardrails", "Guardrails", "escudo", lista.length ? plural(suma(lista.map((g) => g.n)), "activación", "activaciones") : null,
    intervenciones.length ? el("h3", { clase: "subtitulo-panel", texto: "Intervenciones por verificación" }) : null,
    intervenciones.map(([res, filas]) => figuraResultado(res, filas,
      { bloqueada: ["bloqueada", "bloqueadas"], sanitizado: ["sanitizada", "sanitizadas"], marcada: ["marcada", "marcadas"] }[res] || [res, res])),
    aprobadas.length ? el("details", { clase: "plegable" },
      el("summary", {}, el("span", { clase: "plegable-titulo" }, "Aprobadas: ", el("strong", { texto: numero(por("aprobada")) }),
        ` en ${plural(aprobadas.length, "verificación", "verificaciones")}`), el("span", { clase: "plegable-accion", texto: "ver la tabla" })),
      conEtiquetasMono(barras(aprobadas.map((g) => ({ etiqueta: g.verificacion, valor: g.n })),
        { titulo: "Aprobadas por verificación", encabezado: "Verificación", columnaValor: "Activaciones" }))) : null);
}

function configuracion(conf) {
  const dato = (k, v, clase = "mono") => [el("dt", { texto: k }), el("dd", { clase, texto: v ?? "—" })];
  return panel("sec-configuracion", "Configuración activa", "etiqueta", conf.version_configuracion ? `versión ${conf.version_configuracion}` : null,
    el("dl", { clase: "interpretada apilada configuracion" },
      dato("Versión de configuración", conf.version_configuracion),
      dato("Versión del servicio · del corpus", [conf.version_servicio, conf.version_corpus].filter(Boolean).join(" · ") || null),
      ...Object.entries(conf.modelos || {}).flatMap(([k, v]) => dato(MODELOS[k] || `Modelo · ${k}`, v)),
      el("dt", { texto: "Versiones de prompts" }),
      el("dd", {}, Object.keys(conf.versiones_prompts || {}).length
        ? el("ul", { clase: "lista-simple" }, Object.entries(conf.versiones_prompts).map(([k, v]) => el("li", { texto: `${k}: ${v}` })))
        : "—")));
}

/** Uso por modelo: las llamadas en barras y, debajo, el detalle por modelo (modelos en columnas: cabe en media columna). */
function usoPorModelo(m) {
  const modelos = Object.entries(m.modelos || {});
  const filas = [["Llamadas", (v) => numero(v.llamadas)], ["Tokens de entrada", (v) => numero(v.tokens_prompt)],
    ["Tokens de salida", (v) => numero(v.tokens_salida)], ["Tiempo total", (v) => duracion((v.tiempo_ms || 0) / 1000)],
    ["Respaldos", (v) => numero(v.respaldos)], ["Tiempos agotados", (v) => numero(v.tiempos_agotados)], ["JSON inválido", (v) => numero(v.json_invalido)]];
  return panel("sec-modelos", "Uso por modelo", "cpu", modelos.length ? plural(suma(modelos.map(([, v]) => v.llamadas)), "llamada", "llamadas") : null,
    conEtiquetasMono(barras(modelos.map(([k, v]) => ({ etiqueta: k, valor: v.llamadas })),
      { titulo: "Llamadas por modelo", encabezado: "Modelo", columnaValor: "Llamadas" })),
    modelos.length ? el("div", { clase: "desplazable" }, el("table", { clase: "tabla tabla-compacta detalle-modelos" },
      el("caption", { texto: "Detalle por modelo" }),
      el("thead", {}, el("tr", {}, el("th", { scope: "col", texto: "Concepto" }), modelos.map(([k]) => el("th", { scope: "col", clase: "num mono", texto: k })))),
      el("tbody", {}, filas.map(([titulo, valor]) => el("tr", {}, el("th", { scope: "row", texto: titulo }),
        modelos.map(([, v]) => el("td", { clase: "num", texto: valor(v) }))))))) : null);
}

function latenciaPorEndpoint(m) {
  const endpoints = Object.entries(m.latencia_por_endpoint || {}).sort(([, x], [, y]) => (y.p50_ms || 0) - (x.p50_ms || 0));
  return panel("sec-endpoints", "Latencia por endpoint", "servidor", endpoints.length ? plural(suma(endpoints.map(([, v]) => v.n)), "petición", "peticiones") : null,
    conEtiquetasMono(barras(endpoints.map(([k, v]) => ({ etiqueta: k, valor: v.p50_ms || 0, p95: v.p95_ms, n: v.n })),
      { titulo: "p50 por endpoint, con su p95 (del más lento al más rápido)", encabezado: "Endpoint", columnaValor: "p50", formato: ms,
        extras: [{ titulo: "p95", texto: (f) => ms(f.p95) }, { titulo: "Peticiones", texto: (f) => numero(f.n) }] })));
}

function errorDeCarga(texto) {
  return el("section", { clase: "vacio error-carga", "aria-labelledby": "titulo-error-carga" },
    icono("error", "icono-48"),
    el("h2", { id: "titulo-error-carga", texto: "No se pudieron leer las métricas" }),
    el("p", { texto: texto }),
    el("button", { type: "button", clase: "boton secundario", onclick: () => cargar() }, icono("actualizar"), "Reintentar"));
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
    banda.replaceChildren(...cifrasClave(m));
    const vacio = !m.eventos_considerados;
    // Columnas equilibradas: izquierda ≈ accesibilidad + guardrails; derecha ≈ enrutador + retroalimentación
    tablero.replaceChildren(...[
      vacio ? crearMensaje("No hay eventos en este periodo: las secciones muestran solo el estado del archivo. Elige «Todo el historial» para ver todo.", "info") : null,
      latenciaPorCapa(m),
      cache(m, conf),
      el("div", { clase: "reticula columnas-paneles" },
        el("div", { clase: "col-6 columna-paneles" }, accesibilidad(m), guardrails(m)),
        el("div", { clase: "col-6 columna-paneles" }, enrutador(m), retroalimentacion(m))),
      el("div", { clase: "reticula columnas-paneles" },
        el("div", { clase: "col-6 columna-paneles" }, usoPorModelo(m)),
        el("div", { clase: "col-6 columna-paneles" }, conf ? configuracion(conf) : null)),
      latenciaPorEndpoint(m)].filter(Boolean));
    conDatos = true;
    const generado = m.generado ? new Date(m.generado) : new Date();
    mensaje(estado, el("span", {}, "Actualizado ", el("time", { clase: "mono", datetime: generado.toISOString(), texto: fechaIso(generado) }),
      ` · ${plural(m.eventos_considerados ?? 0, "evento", "eventos")}`), "ok");
    anunciar("Métricas actualizadas");
  } catch (e) {
    if (mio !== turno) return;
    // Sin datos previos, el panel explica el error con «Reintentar»: en el encabezado basta una línea corta
    mensaje(estado, conDatos ? `No se pudo actualizar: ${e.message}` : "No se pudieron leer las métricas.");
    if (!conDatos) {
      banda.replaceChildren();
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
