// Inicio · v4 «Mesa de luz»: la búsqueda arriba, la hoja de contactos del archivo (GET /api/documentos, 24 fotogramas
// por hoja, numerados por su posición en el archivo), el estado del sistema en una línea con su detalle desplegable
// (GET /api/health), las cifras en una frase (GET /api/metricas), las 7 capas con su p50 y su n, y un índice discreto con
// cifras en vivo (más GET /api/duplicados). Los nombres de los componentes vienen de la API: la web no conoce los
// recursos internos (R8).
// Carga: /health cada 30 s (cada 10 s solo mientras los modelos se precalientan o algo falla); /metricas y /duplicados
// una vez. Nada se pide con la pestaña oculta, y al volver se refresca /health si ya pasó su intervalo.
import { api, anunciar, el, insignia } from "./api.js";
import * as comun from "./comun.js";

const { CAPAS, ORDEN_CAPAS, crearMensaje, cuandoVisible, miniatura, numero, porcentaje, segundos, verFotoGuardada } = comun;
const INTERVALO_S = 30;
const INTERVALO_ARRANQUE_S = 10;
const POR_HOJA = 24;
const NBSP = " ";   // la cifra y su unidad nunca se separan de línea

const plural = (n, uno, varios) => `${numero(n)}${NBSP}${n === 1 ? uno : varios}`;
/** Trazo de lápiz graso (comun.js · marcaLapiz); si la base aún no lo tiene, no se dibuja nada. */
const lapiz = (tipo) => (typeof comun.marcaLapiz === "function" ? comun.marcaLapiz(tipo) : null);

// ── La hoja de contactos ──
const tira = document.getElementById("tira");
const tituloHoja = document.getElementById("titulo-hoja");
const rangoHoja = document.getElementById("hoja-rango");
const botonAnterior = document.getElementById("hoja-anterior");
const botonSiguiente = document.getElementById("hoja-siguiente");
const eleccion = document.getElementById("eleccion");
let hoja = Math.max(1, Number.parseInt(new URLSearchParams(location.search).get("hoja"), 10) || 1);
let totalHojas = null;
let turnoHoja = 0;

/** El fotograma elegido queda circulado con lápiz graso y su línea dice qué es y cómo abrir su ficha. */
function elegir(cuadro, d) {
  for (const otro of tira.querySelectorAll(".cuadro.marcado")) otro.classList.remove("marcado");
  cuadro.classList.add("marcado");
  eleccion.replaceChildren(el("strong", { clase: "eleccion-num", texto: numero(d.numero) }), " ", d.titular || d.documento_id, " ",
    el("a", { href: `catalogar.html?doc=${encodeURIComponent(d.documento_id)}`, texto: "Abrir la ficha" }));
  eleccion.hidden = false;
  verFotoGuardada(d.documento_id, { titulo: d.titular || `Fotograma ${d.numero}` });
}

function cuadro(d) {
  const titular = d.titular || d.nombre || d.documento_id;
  const alt = d.texto_alternativo || d.titular || `Fotograma ${d.numero} (foto sin ficha)`;
  const item = el("li", { clase: "cuadro" });
  item.append(
    el("button", { type: "button", clase: "cuadro-foto", title: titular, onclick: () => elegir(item, d) },
      miniatura(d.documento_id, { alt }), el("span", { clase: "solo-lectores", texto: ` (fotograma ${d.numero}: ver en grande)` })),
    el("span", { clase: "cuadro-num", "aria-hidden": "true", texto: numero(d.numero) }));
  const trazo = lapiz("circulo");
  if (trazo) item.append(trazo);
  return item;
}

async function cargarHoja(n) {
  const turno = ++turnoHoja;
  tira.setAttribute("aria-busy", "true");
  if (!tira.children.length) {
    tira.replaceChildren(...Array.from({ length: POR_HOJA }, () => el("li", { clase: "cuadro cargando", "aria-hidden": "true" },
      el("span", { clase: "esqueleto foto" }))));
  }
  try {
    const { cuerpo } = await api(`/documentos?tipo=foto&pagina=${n}&por_pagina=${POR_HOJA}`);
    if (turno !== turnoHoja) return;
    const total = cuerpo.total ?? 0;
    totalHojas = Math.max(1, Math.ceil(total / POR_HOJA));
    if (n > totalHojas && total) { hoja = totalHojas; cargarHoja(hoja); return; }
    hoja = n;
    const desde = (n - 1) * POR_HOJA;
    const documentos = cuerpo.documentos || [];
    // Numerados por su posición en el archivo; solo fotos del archivo de referencia (nunca fotos subidas, up-…)
    const cuadros = documentos.map((d, i) => ({ ...d, numero: desde + i + 1 })).filter((d) => d.documento_id.startsWith("xm-"));
    tira.replaceChildren(...(cuadros.length ? cuadros.map(cuadro)
      : [el("li", { clase: "hoja-vacia" }, crearMensaje("Esta hoja no tiene fotos del archivo de referencia.", "info"))]));
    tituloHoja.textContent = `Hoja ${numero(n)} de ${numero(totalHojas)}`;
    rangoHoja.textContent = documentos.length
      ? `Fotogramas ${numero(desde + 1)} a ${numero(desde + documentos.length)} de las ${plural(total, "foto", "fotos")} del archivo.`
      : `El archivo tiene ${plural(total, "foto", "fotos")}.`;
    botonAnterior.disabled = n <= 1;
    botonSiguiente.disabled = n >= totalHojas;
    eleccion.hidden = true;
    history.replaceState(null, "", n === 1 ? location.pathname : `${location.pathname}?hoja=${n}`);
  } catch (e) {
    if (turno !== turnoHoja) return;
    tira.replaceChildren(el("li", { clase: "hoja-vacia" }, crearMensaje(e.message, "error")));
    rangoHoja.textContent = "No se pudo leer el archivo.";
  } finally {
    if (turno === turnoHoja) tira.removeAttribute("aria-busy");
  }
}

function cambiarHoja(delta) {
  const destino = hoja + delta;
  if (destino < 1 || (totalHojas && destino > totalHojas)) return;
  cargarHoja(destino).then(() => anunciar(tituloHoja.textContent));
}
botonAnterior.addEventListener("click", () => cambiarHoja(-1));
botonSiguiente.addEventListener("click", () => cambiarHoja(1));

// ── Estado del sistema: una línea y, desplegable, una fila por componente ──
/** «45 s», «12 min», «3 h 5 min». */
function hace(segundosActivo) {
  const s = Math.max(0, Math.round(segundosActivo));
  if (s < 60) return `${s}${NBSP}s`;
  if (s < 3600) return `${Math.floor(s / 60)}${NBSP}min`;
  const m = Math.floor((s % 3600) / 60);
  return `${Math.floor(s / 3600)}${NBSP}h${m ? ` ${m}${NBSP}min` : ""}`;
}

const NOMBRE_FILAS = { documentos: ["documento", "documentos"], fichas: ["ficha", "fichas"], cache: ["entrada", "entradas"] };
const nombreCorto = (c) => (c.nombre || "Componente").replace(/\s*\([^)]*\)\s*$/, "");

/** Lo que se midió de cada componente, en una frase corta. */
function detalle(c) {
  if (c.estado === "error") return c.error || "No disponible";
  const partes = [];
  if (c.version) partes.push(`versión ${c.version}`);
  if (c.modelos_requeridos) {
    const faltan = (c.modelos_faltantes || []).length;
    partes.push(faltan ? `faltan ${numero(faltan)} de ${numero(c.modelos_requeridos.length)} modelos`
      : `${numero((c.modelos_cargados || []).length)} de ${numero(c.modelos_requeridos.length)} modelos en memoria`);
  }
  if (c.colecciones) {
    const puntos = Object.values(c.colecciones);
    partes.push(`${plural(puntos.reduce((s, n) => s + (n ?? 0), 0), "vector", "vectores")} en ${plural(puntos.length, "colección", "colecciones")}`);
  }
  if (c.filas) partes.push(...Object.entries(c.filas).map(([t, n]) => (NOMBRE_FILAS[t] ? plural(n, ...NOMBRE_FILAS[t]) : `${t}: ${numero(n)}`)));
  if (c.segundos_activo !== undefined) partes.push(`activo desde hace ${hace(c.segundos_activo)}`);
  const texto = partes.join(", ");
  return texto ? texto[0].toUpperCase() + texto.slice(1) : c.descripcion || "";
}

function filaComponente(c) {
  return el("article", { clase: `tarjeta componente estado-${c.estado || "otro"}` },
    el("h3", { clase: "componente-nombre", texto: c.nombre || "Componente" }),
    el("p", { clase: "componente-estado" }, insignia(c.estado)),
    el("p", { clase: "componente-detalle", texto: detalle(c) }),
    c.descripcion ? el("p", { clase: "componente-descripcion", texto: c.descripcion }) : null);
}

/** La línea de estado, en prosa. */
function resumenEstado(cuerpo) {
  const comps = Object.values(cuerpo.componentes || {});
  const modelos = comps.find((c) => c.modelos_requeridos);
  const enMemoria = modelos && !(modelos.modelos_faltantes || []).length
    ? ` y ${plural((modelos.modelos_cargados || []).length, "modelo está", "modelos están")} en memoria` : "";
  if (cuerpo.estado === "ok") return `Todo local: ${comps.length === 1 ? "el componente responde" : `los ${numero(comps.length)} componentes responden`}${enMemoria}.`;
  const conFallas = comps.filter((c) => c.estado !== "ok").map(nombreCorto);
  return conFallas.length ? `Revisa ${conFallas.join(" y ")}: el resto responde.` : "Algún componente no respondió como se esperaba.";
}

let anterior = null;
let ultimaSalud = 0;
let temporizador = null;
let intervalo = INTERVALO_S;
const datos = { salud: null, metricas: null, duplicados: null };   // para el índice

async function actualizarSalud() {
  const contenedor = document.getElementById("componentes");
  const general = document.getElementById("estado-general");
  const resumen = document.getElementById("estado-resumen");
  ultimaSalud = Date.now();
  try {
    const { cuerpo } = await api("/health", { aceptar: [503] });
    datos.salud = cuerpo;
    contenedor.replaceChildren(...Object.values(cuerpo.componentes || {}).map(filaComponente));
    general.replaceChildren(el("span", { clase: "solo-lectores", texto: "Estado general: " }), insignia(cuerpo.estado));
    resumen.textContent = resumenEstado(cuerpo);
    const pre = cuerpo.precalentamiento || {};
    const textoPre = pre.estado === "en_curso" ? "Los modelos se están cargando en memoria."
      : pre.estado === "listo" ? `Los modelos quedaron listos en memoria en ${numero(pre.segundos)}${NBSP}s.`
      : pre.estado === "error" ? "No se pudo cargar algún modelo en memoria." : "";
    document.getElementById("estado-configuracion").replaceChildren("Versión de configuración ",
      el("span", { clase: "mono", texto: cuerpo.versiones?.configuracion || "—" }), `. ${textoPre}`.trimEnd());
    if (anterior !== cuerpo.estado) anunciar(`Estado del sistema: ${cuerpo.estado === "ok" ? "en verde" : cuerpo.estado}`);
    anterior = cuerpo.estado;
    intervalo = cuerpo.estado === "ok" && pre.estado !== "en_curso" ? INTERVALO_S : INTERVALO_ARRANQUE_S;
    pintarIndice();
  } catch (e) {
    general.replaceChildren(el("span", { clase: "solo-lectores", texto: "Estado general: " }), insignia("sin_conexion"));
    resumen.textContent = e.message;
    if (anterior !== "sin_conexion") anunciar(e.message);
    anterior = "sin_conexion";
    intervalo = INTERVALO_ARRANQUE_S;
  } finally {
    contenedor.removeAttribute("aria-busy");
  }
}

function programar() {
  clearTimeout(temporizador);
  temporizador = null;
  if (document.hidden) return;
  temporizador = setTimeout(async () => { await actualizarSalud(); programar(); }, intervalo * 1000);
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) { clearTimeout(temporizador); temporizador = null; return; }
  if (!ultimaSalud) return;   // la primera carga la hace cuandoVisible()
  if (Date.now() - ultimaSalud >= intervalo * 1000) actualizarSalud().then(programar);
  else programar();
});

// ── El archivo en una frase: 4 cifras ──
const cifra = (valor) => el("span", { clase: "cifra", texto: valor });

function fraseCifras(a) {
  const fotos = a.fotos ?? 0;
  const porRevisar = a.requiere_revision ?? 0;
  return [
    "El archivo tiene ", cifra(numero(fotos)), `${NBSP}${fotos === 1 ? "foto" : "fotos"}; `,
    cifra(numero(a.fichas_validadas ?? 0)), `${NBSP}tienen la ficha validada por el archivista, el `,
    cifra(porcentaje(a.porcentaje_alt_validado)), " tiene texto alternativo validado y ",
    cifra(numero(porRevisar)), porRevisar === 1 ? `${NBSP}ficha espera revisión.` : `${NBSP}fichas esperan revisión.`,
  ];
}

// ── Cómo se genera una ficha: las 7 capas en orden, con p50 y n medidos y una barra con escala común ──
const ETAPAS = {
  guardrails_entrada: "Valida el archivo y quita el GPS y los datos del autor.",
  cache: "Si la foto ya se catalogó, reutiliza su ficha.",
  contexto: "Reúne fotos similares, normas y términos del tesauro.",
  enrutador: "Elige la ruta rápida o la completa.",
  modelo_vision: "Describe lo que se ve en la foto.",
  modelo_composicion: "Redacta la ficha IPTC y cita sus fuentes.",
  guardrails_salida: "Revisa el texto alternativo, los datos sensibles y las fuentes.",
};

function pintarTuberia() {
  document.getElementById("tuberia").replaceChildren(...ORDEN_CAPAS.map((clave, i) => el("li", { clase: "etapa", "data-capa": clave },
    el("span", { clase: "etapa-numero", "aria-hidden": "true", texto: String(i + 1) }),
    el("div", { clase: "etapa-texto" }, el("h3", { texto: CAPAS[clave] || clave }), el("p", { texto: ETAPAS[clave] || "" })),
    el("span", { clase: "etapa-barra", "aria-hidden": "true" }, el("span", { clase: "etapa-relleno" })),
    el("p", { clase: "etapa-p50" }, el("span", { clase: "solo-lectores", texto: "Tiempo típico (p50): " }), el("span", { clase: "valor", texto: "—" })),
    el("p", { clase: "etapa-n" }, el("span", { clase: "solo-lectores", texto: "Mediciones: " }), el("span", { "aria-hidden": "true", texto: "n" + NBSP }),
      el("span", { clase: "valor", texto: "—" })))));
}

function tiemposTuberia(m) {
  const capas = m.latencia_por_capa?.fichas || {};
  const etapas = [...document.querySelectorAll("#tuberia .etapa")];
  const maximo = Math.max(1e-9, ...etapas.map((e) => capas[e.dataset.capa]?.p50_ms).filter((v) => typeof v === "number"));
  for (const etapa of etapas) {
    const medida = capas[etapa.dataset.capa];
    if (typeof medida?.p50_ms !== "number") continue;
    etapa.querySelector(".etapa-p50 .valor").textContent = segundos(medida.p50_ms);
    if (medida.n !== undefined) etapa.querySelector(".etapa-n .valor").textContent = numero(medida.n);
    etapa.querySelector(".etapa-relleno").style.width = `${Math.max(0, Math.min(100, (medida.p50_ms / maximo) * 100)).toFixed(2)}%`;
  }
  // El total es la mediana de punta a punta que mide el servicio: NO es la suma de las medianas de las capas
  const total = capas.total;
  if (total && typeof total.p50_ms === "number") {
    const p95 = typeof total.p95_ms === "number" ? ` y p95${NBSP}${segundos(total.p95_ms)}` : "";
    document.getElementById("tuberia-total").replaceChildren("Tiempo total medido de punta a punta: ",
      el("span", { clase: "mono", texto: `p50${NBSP}${segundos(total.p50_ms)}${p95}` }),
      total.n ? ` en ${plural(total.n, "ficha", "fichas")}. Las medianas de las capas no se suman.` : ".");
    document.getElementById("tuberia-total").hidden = false;
    document.getElementById("tuberia-auxiliar").textContent = "Las 7 capas que recorre cada foto, en orden, con su tiempo típico (p50) y cuántas veces se midió (n). Las barras comparten la escala.";
  }
}

// ── Índice: los 5 módulos con una cifra en vivo ──
function datoIndice(id, texto) {
  const nodo = document.getElementById(id);
  if (nodo && texto) nodo.textContent = texto;
}

function pintarIndice() {
  const a = datos.metricas?.accesibilidad;
  const fichas = datos.metricas?.latencia_por_capa?.fichas?.total;
  const busquedas = datos.metricas?.latencia_por_capa?.busquedas?.total;
  const filas = datos.salud?.componentes?.almacen?.filas;
  if (a) datoIndice("dato-catalogar", `${plural(a.requiere_revision ?? 0, "ficha", "fichas")} por revisar`);
  if (busquedas?.n !== undefined) datoIndice("dato-buscar", `${plural(busquedas.n, "búsqueda medida", "búsquedas medidas")}`);
  if (Array.isArray(datos.duplicados)) datoIndice("dato-duplicados", plural(datos.duplicados.length, "grupo de casi duplicados", "grupos de casi duplicados"));
  if (filas?.documentos !== undefined) datoIndice("dato-archivo", plural(filas.documentos, "documento", "documentos"));
  if (fichas?.n !== undefined) datoIndice("dato-metricas", plural(fichas.n, "ficha medida", "fichas medidas"));
}

async function actualizarArchivo() {
  const contenedor = document.getElementById("cifras");
  try {
    const { cuerpo: m } = await api("/metricas");
    datos.metricas = m;
    contenedor.replaceChildren(el("p", {}, ...fraseCifras(m.accesibilidad || {})));
    tiemposTuberia(m);
    pintarIndice();
  } catch (e) {
    contenedor.replaceChildren(crearMensaje(e.message, "error"));
  } finally {
    contenedor.removeAttribute("aria-busy");
  }
}

async function actualizarDuplicados() {
  try {
    const { cuerpo } = await api("/duplicados");
    datos.duplicados = Array.isArray(cuerpo) ? cuerpo : cuerpo?.grupos ?? null;
    pintarIndice();
  } catch {
    // Sin el dato, el enlace del índice funciona igual
  }
}

pintarTuberia();
cuandoVisible(() => {
  cargarHoja(hoja);
  actualizarSalud().then(programar);
  actualizarArchivo();
  actualizarDuplicados();
});
