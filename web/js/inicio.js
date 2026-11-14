// Inicio · «Resumen del archivo»: estado del sistema (GET /api/health), el archivo en cifras (GET /api/metricas), una
// muestra fija de 12 fotos reales del archivo (GET /api/fichas/{id}), cifras en vivo por módulo (las mismas respuestas
// más GET /api/duplicados) y la tubería de las 7 capas con su p50 y su n medidos. Los nombres de los componentes vienen
// de la API: la web no conoce los recursos internos (R8).
// Carga: /health cada 30 s (cada 10 s solo mientras los modelos se precalientan o algo falla); /metricas y /duplicados
// una vez. Nada se pide con la pestaña oculta, y al volver se refresca /health si ya pasó su intervalo.
import { api, anunciar, el, insignia } from "./api.js";
import {
  CAPAS, ORDEN_CAPAS, crearMensaje, cuandoVisible, medidor, miniatura, numero, porcentaje, segundos, verFotoGuardada,
} from "./comun.js";
import { icono, ilustracion } from "./iconos.js";

const INTERVALO_S = 30;
const INTERVALO_ARRANQUE_S = 10;
const NBSP = " ";   // la cifra y su unidad nunca se separan de línea

const plural = (n, uno, varios) => `${numero(n)}${NBSP}${n === 1 ? uno : varios}`;

// ── Muestra del archivo ──
// 12 fotos REALES del archivo de referencia, revisadas una por una: sin personas, con buena luz y tres de cada tema
// (paisaje, arquitectura, comida y objetos), alternados. Nunca fotos subidas (up-…). Si alguna falla (ficha o imagen),
// se reemplaza con otra del listado del archivo, también solo xm-….
const MUESTRA = [
  "xm-05ab8cb823b8df06",   // paisaje: estanque entre montañas
  "xm-8a5556c0389f3bd0",   // arquitectura: iglesia colorida
  "xm-98e6f9ee8c958a9e",   // comida: espagueti
  "xm-0664e168198cede3",   // objetos: dos cámaras antiguas
  "xm-af04ae2350cc12b5",   // paisaje: isla con montaña
  "xm-99fd7bb792823a4a",   // arquitectura: edificio clásico
  "xm-fa1d5d16b3c3323e",   // comida: pan de centeno
  "xm-944707c24b36589a",   // objetos: barco de vela
  "xm-747af27bee10e0c7",   // paisaje: riachuelo entre montañas
  "xm-d7ad8d5cb493f400",   // arquitectura: torre de iglesia ortodoxa
  "xm-f1d4e1ad5e259552",   // comida: pastelitos
  "xm-ebd694da1d01b4b3",   // objetos: flor azul
];
const usadas = new Set(MUESTRA);
let reservas = null;

/** Siguiente foto de reserva del archivo (solo xm-…, con titular y sin repetir), o null. */
async function reserva() {
  reservas ||= api("/documentos?tipo=foto&por_pagina=60&pagina=2")
    .then(({ cuerpo }) => (cuerpo?.documentos || [])
      .filter((d) => d.documento_id.startsWith("xm-") && d.titular)
      .map((d) => ({ id: d.documento_id, titular: d.titular, alt: d.texto_alternativo || d.titular })))
    .catch(() => []);
  const foto = (await reservas).find((d) => !usadas.has(d.id));
  if (foto) usadas.add(foto.id);
  return foto || null;
}

function fotoDeMuestra(foto, i) {
  const img = miniatura(foto.id, { alt: foto.alt });
  // El número de fotograma va impreso sobre la esquina de la foto, como en una hoja de contactos; el pie, el titular
  // en dos líneas como máximo (el entero, en title y en el visor)
  const item = el("li", {}, el("figure", { clase: "montura" },
    el("button", { type: "button", clase: "boton-imagen", onclick: () => verFotoGuardada(foto.id, { titulo: foto.titular }) },
      img, el("span", { clase: "fotograma", "aria-hidden": "true", texto: String(i + 1).padStart(2, "0") }),
      el("span", { clase: "solo-lectores", texto: " (ver en grande con su ficha)" })),
    el("figcaption", { title: foto.titular }, el("span", { clase: "muestra-titular", texto: foto.titular }))));
  // Si la imagen no carga, otra foto del archivo ocupa su lugar (o el hueco se cierra)
  img.addEventListener("error", async () => {
    const otra = await reserva();
    if (otra) item.replaceWith(fotoDeMuestra(otra, i));
    else item.remove();
  }, { once: true });
  return item;
}

async function cargarMuestra() {
  const lista = document.getElementById("muestra");
  lista.replaceChildren(...MUESTRA.map(() => el("li", { clase: "cargando", "aria-hidden": "true" },
    el("span", { clase: "montura" }, el("span", { clase: "esqueleto foto" }), el("span", { clase: "esqueleto linea" })))));
  const fotos = await Promise.all(MUESTRA.map(async (id) => {
    try {
      const { cuerpo } = await api(`/fichas/${encodeURIComponent(id)}`, { aceptar: [404] });
      const f = cuerpo?.ficha;
      return f?.titular ? { id, titular: f.titular, alt: f.texto_alternativo || f.titular } : await reserva();
    } catch {
      return reserva();
    }
  }));
  const validas = fotos.filter(Boolean);
  lista.replaceChildren(...(validas.length ? validas.map(fotoDeMuestra)
    : [el("li", { clase: "vacio" }, ilustracion("vacio"), el("h3", { texto: "No se pudo cargar la muestra" }),
      el("p", { texto: "El archivo no respondió. Revisa el estado del sistema arriba y vuelve a cargar la página." }))]));
  lista.removeAttribute("aria-busy");
}

// ── Estado del sistema: una insignia general y, por subsistema, ✓ (o ⚠ / ✕), nombre y un detalle ──
/** «45 s», «12 min», «3 h 5 min». */
function hace(segundosActivo) {
  const s = Math.max(0, Math.round(segundosActivo));
  if (s < 60) return `${s}${NBSP}s`;
  if (s < 3600) return `${Math.floor(s / 60)}${NBSP}min`;
  const m = Math.floor((s % 3600) / 60);
  return `${Math.floor(s / 3600)}${NBSP}h${m ? ` ${m}${NBSP}min` : ""}`;
}

// «Nombre (Tecnología)» → nombre corto en la celda y la tecnología al inicio del detalle
const CON_TECNOLOGIA = /^(.+?)\s*\(([^)]+)\)\s*$/;
const NOMBRE_FILAS = { documentos: ["documento", "documentos"], fichas: ["ficha", "fichas"], cache: ["entrada", "entradas"] };
// Icono y texto (para lectores de pantalla) de cada estado: el icono cambia de forma, no solo de color
const MARCA_ESTADO = { ok: ["check", "en verde"], degradado: ["alerta", "degradado"], error: ["error", "con fallas"] };

function partesNombre(c) {
  const m = CON_TECNOLOGIA.exec(c.nombre || "");
  return m ? { nombre: m[1], tecnologia: m[2] } : { nombre: c.nombre || "Componente", tecnologia: null };
}

/** Detalle corto (una línea a 1280 px en 5 columnas); el largo va en title. */
function detalle(c, tecnologia) {
  if (c.estado === "error") return c.error || "No disponible";
  let texto = "";
  if (c.modelos_requeridos) {
    const requeridos = c.modelos_requeridos.length;
    const faltan = (c.modelos_faltantes || []).length;
    texto = faltan ? `faltan ${numero(faltan)} de ${numero(requeridos)} modelos`
      : `${numero((c.modelos_cargados || []).length)}/${numero(requeridos)} en memoria`;
  } else if (c.colecciones) {
    const puntos = Object.values(c.colecciones);
    texto = puntos.length ? plural(puntos.reduce((s, n) => s + (n ?? 0), 0), "vector", "vectores") : "sin colecciones";
  } else if (c.filas) {
    const [tabla, n] = Object.entries(c.filas)[0] || [];
    texto = tabla === undefined ? "" : NOMBRE_FILAS[tabla] ? plural(n, ...NOMBRE_FILAS[tabla]) : `${tabla}: ${numero(n)}`;
  } else if (c.segundos_activo !== undefined) {
    texto = `activo hace ${hace(c.segundos_activo)}`;
  }
  return [tecnologia, texto].filter(Boolean).join(" · ");
}

/** Detalle completo para el `title`: todas las filas, colecciones, versión y descripción. */
function detalleCompleto(c) {
  const partes = [c.nombre, c.version ? `versión ${c.version}` : null];
  if (c.modelos_requeridos) partes.push(`${numero((c.modelos_cargados || []).length)} de ${numero(c.modelos_requeridos.length)} modelos en memoria`);
  if (c.colecciones) partes.push(Object.entries(c.colecciones).map(([n, p]) => `${n} ${numero(p ?? 0)}`).join(" · "));
  if (c.filas) partes.push(Object.entries(c.filas).map(([t, n]) => (NOMBRE_FILAS[t] ? plural(n, ...NOMBRE_FILAS[t]) : `${t}: ${numero(n)}`)).join(" · "));
  if (c.segundos_activo !== undefined) partes.push(`activo desde hace ${hace(c.segundos_activo)}`);
  if (c.estado === "error" && c.error) partes.push(c.error);
  partes.push(c.descripcion);
  return partes.filter(Boolean).join(". ");
}

function celdaComponente(c) {
  const { nombre, tecnologia } = partesNombre(c);
  const [nombreIcono, textoEstado] = MARCA_ESTADO[c.estado] || ["info", c.estado || "sin dato"];
  return el("article", { clase: `tarjeta componente estado-${MARCA_ESTADO[c.estado] ? c.estado : "otro"}`, title: detalleCompleto(c) },
    el("h3", { clase: "componente-nombre" }, icono(nombreIcono, "componente-marca"),
      el("span", { clase: "una-linea", texto: nombre }), el("span", { clase: "solo-lectores", texto: `: ${textoEstado}` })),
    el("p", { clase: "componente-detalle una-linea", texto: detalle(c, tecnologia) }));
}

let anterior = null;
let ultimaSalud = 0;
let temporizador = null;
let intervalo = INTERVALO_S;
const datos = { salud: null, metricas: null, duplicados: null };   // para el resumen por módulo y el subtítulo
// Sexta celda de la franja (configuración y precalentamiento): se ve en 3×2 y en móvil; en una fila de 5, esos datos
// van en la cabecera del panel. No es .tarjeta: las 5 tarjetas son los componentes.
const celdaConfiguracion = document.querySelector("#componentes .componente-config");

async function actualizarSalud() {
  const contenedor = document.getElementById("componentes");
  const general = document.getElementById("estado-general");
  ultimaSalud = Date.now();
  try {
    const { cuerpo } = await api("/health", { aceptar: [503] });
    datos.salud = cuerpo;
    contenedor.replaceChildren(...Object.values(cuerpo.componentes || {}).map(celdaComponente), celdaConfiguracion);
    contenedor.classList.remove("con-mensaje");
    general.replaceChildren(el("span", { clase: "solo-lectores", texto: "Estado general: " }), insignia(cuerpo.estado));
    const pre = cuerpo.precalentamiento || {};
    const textoPre = pre.estado === "en_curso" ? "cargando los modelos…"
      : pre.estado === "listo" ? `modelos listos (${numero(pre.segundos)}${NBSP}s)`
      : pre.estado === "error" ? "no se pudo cargar algún modelo" : "";
    for (const nodo of document.querySelectorAll(".version-configuracion")) {
      nodo.replaceChildren(nodo.closest(".estado-meta") ? "Configuración " : "",
        el("span", { clase: "mono", texto: cuerpo.versiones?.configuracion || "—" }));
    }
    for (const nodo of document.querySelectorAll(".precalentamiento")) nodo.textContent = textoPre;
    celdaConfiguracion.title = `Versión de configuración ${cuerpo.versiones?.configuracion || "—"}; ${textoPre}`;
    if (anterior !== cuerpo.estado) anunciar(`Estado del sistema: ${cuerpo.estado === "ok" ? "en verde" : cuerpo.estado}`);
    anterior = cuerpo.estado;
    intervalo = cuerpo.estado === "ok" && pre.estado !== "en_curso" ? INTERVALO_S : INTERVALO_ARRANQUE_S;
    pintarModulos();
  } catch (e) {
    general.replaceChildren(el("span", { clase: "solo-lectores", texto: "Estado general: " }), insignia("sin_conexion"));
    // Sin datos previos, la franja explica el problema; con datos, se conservan los últimos conocidos
    if (!contenedor.querySelector(".componente.tarjeta:not(.cargando)")) {
      contenedor.replaceChildren(crearMensaje(e.message, "error"));
      contenedor.classList.add("con-mensaje");
    }
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

// ── El archivo en cifras ──
function cifra(nombreIcono, valor, etiqueta, extra = null) {
  return el("article", { clase: "cifra" }, icono(nombreIcono),
    el("p", { clase: "cifra-valor", texto: valor }), el("p", { clase: "cifra-etiqueta", texto: etiqueta }), extra);
}

function pintarCifras(a) {
  const porRevisar = a.requiere_revision ?? 0;
  return [
    cifra("foto", numero(a.fotos ?? 0), "fotos en el archivo"),
    cifra("check", numero(a.fichas_validadas ?? 0), "fichas validadas por el archivista"),
    // Más es mejor: el medidor no pasa a «aviso» al acercarse al total (aviso > 1)
    cifra("ojo", porcentaje(a.porcentaje_alt_validado), "de las fotos con texto alternativo validado",
      medidor(a.alt_validado ?? 0, a.fotos ?? 0, { aviso: 1.01, unidad: "" })),
    // Sin pendientes no hay nada que advertir: ✓ en vez del triángulo
    cifra(porRevisar ? "alerta" : "check", numero(porRevisar), "fichas por revisar",
      el("p", { clase: "cifra-nota", texto: `${plural(a.borrador ?? 0, "borrador", "borradores")} · ${numero(a.sin_ficha ?? 0)}${NBSP}sin${NBSP}ficha` })),
  ];
}

// ── Resumen operativo (subtítulo) y cifras en vivo por módulo ──
function datoModulo(id, valor, texto) {
  const nodo = document.getElementById(id);
  if (!nodo || valor === null || valor === undefined) return;
  nodo.replaceChildren(el("span", { clase: "acceso-cifra", texto: numero(valor) }), `${NBSP}${texto}`);
}

function pintarModulos() {
  const a = datos.metricas?.accesibilidad;
  const fichas = datos.metricas?.latencia_por_capa?.fichas?.total;
  const busquedas = datos.metricas?.latencia_por_capa?.busquedas?.total;
  const filas = datos.salud?.componentes?.almacen?.filas;
  if (a) datoModulo("dato-catalogar", a.fotos ?? 0, (a.fotos ?? 0) === 1 ? "foto en el archivo" : "fotos en el archivo");
  if (busquedas?.n !== undefined) {
    datoModulo("dato-buscar", busquedas.n, `${busquedas.n === 1 ? "búsqueda" : "búsquedas"}${typeof busquedas.p50_ms === "number" ? ` · p50${NBSP}${segundos(busquedas.p50_ms)}` : ""}`);
  }
  if (Array.isArray(datos.duplicados)) {
    datoModulo("dato-duplicados", datos.duplicados.length, datos.duplicados.length === 1 ? "grupo de casi duplicados" : "grupos de casi duplicados");
  }
  if (filas?.documentos !== undefined) datoModulo("dato-archivo", filas.documentos, filas.documentos === 1 ? "documento guardado" : "documentos guardados");
  if (fichas?.n !== undefined) datoModulo("dato-metricas", fichas.n, fichas.n === 1 ? "ficha medida" : "fichas medidas");
  // Subtítulo: una línea operativa con datos que la página ya muestra
  if (a) {
    document.getElementById("resumen-operativo").textContent =
      `${plural(a.fotos ?? 0, "foto catalogada", "fotos catalogadas")}, ${numero(a.fichas_validadas ?? 0)}${NBSP}con ficha validada y `
      + `${numero(a.requiere_revision ?? 0)}${NBSP}por revisar; todo se procesa en este equipo.`;
  }
}

// ── Cómo se genera una ficha: las 7 capas en orden, con p50 y n medidos y una barra con escala común ──
const ETAPAS = {
  guardrails_entrada: ["escudo", "Valida el archivo y quita el GPS y los datos del autor."],
  cache: ["rayo", "Si la foto ya se catalogó, reutiliza su ficha."],
  contexto: ["libros", "Reúne fotos similares, normas y términos del tesauro."],
  enrutador: ["bifurcacion", "Elige la ruta rápida o la completa."],
  modelo_vision: ["ojo", "Describe lo que se ve en la foto."],
  modelo_composicion: ["pluma", "Redacta la ficha IPTC y cita sus fuentes."],
  guardrails_salida: ["escudo-check", "Revisa el texto alternativo, los datos sensibles y las fuentes."],
};

function pintarTuberia() {
  document.getElementById("tuberia").replaceChildren(...ORDEN_CAPAS.map((clave, i) => {
    const [nombreIcono, texto] = ETAPAS[clave] || ["info", ""];
    const relleno = el("span", { clase: "etapa-relleno" });
    return el("li", { clase: "etapa", "data-capa": clave },
      el("span", { clase: "etapa-numero", "aria-hidden": "true", texto: String(i + 1).padStart(2, "0") }),
      icono(nombreIcono, "etapa-icono"),
      el("div", { clase: "etapa-texto" }, el("h3", { texto: CAPAS[clave] || clave }), el("p", { texto })),
      el("span", { clase: "etapa-barra", "aria-hidden": "true" }, relleno),
      el("p", { clase: "etapa-p50" }, el("span", { clase: "solo-lectores", texto: "Tiempo típico (p50): " }), el("span", { clase: "valor", texto: "—" })),
      el("p", { clase: "etapa-n" }, el("span", { clase: "solo-lectores", texto: "Mediciones: " }), el("span", { "aria-hidden": "true", texto: "n " }), el("span", { clase: "valor", texto: "—" })));
  }));
}

function tiemposTuberia(m) {
  const capas = m.latencia_por_capa?.fichas || {};
  const etapas = [...document.querySelectorAll("#tuberia .etapa")];
  const p50s = etapas.map((e) => capas[e.dataset.capa]?.p50_ms).filter((v) => typeof v === "number");
  const maximo = Math.max(1e-9, ...p50s);   // escala común: la capa más lenta llena la barra
  for (const etapa of etapas) {
    const medida = capas[etapa.dataset.capa];
    if (typeof medida?.p50_ms !== "number") continue;
    etapa.querySelector(".etapa-p50 .valor").textContent = segundos(medida.p50_ms);
    if (medida.n !== undefined) etapa.querySelector(".etapa-n .valor").textContent = numero(medida.n);
    etapa.querySelector(".etapa-relleno").style.width = `${Math.max(0, Math.min(100, (medida.p50_ms / maximo) * 100)).toFixed(2)}%`;
    etapa.classList.toggle("dominante", medida.p50_ms === maximo);
  }
  // El total es la mediana de punta a punta que mide el servicio: NO es la suma de las medianas de las capas
  const total = capas.total;
  if (total && typeof total.p50_ms === "number") {
    const pie = document.getElementById("tuberia-total");
    const p95 = typeof total.p95_ms === "number" ? ` · p95${NBSP}${segundos(total.p95_ms)}` : "";
    pie.replaceChildren(icono("reloj"),
      el("span", { texto: "Tiempo total medido de punta a punta:" }),
      el("span", { clase: "mono", texto: `p50${NBSP}${segundos(total.p50_ms)}${p95}` }),
      total.n ? el("span", { clase: "suave", texto: `(${plural(total.n, "ficha", "fichas")}; las medianas de las capas no se suman)` }) : null);
    pie.hidden = false;
    document.getElementById("tuberia-auxiliar").textContent = "p50 y n de cada capa en las fichas medidas · escala común";
  }
}

async function actualizarArchivo() {
  const contenedor = document.getElementById("cifras");
  try {
    const { cuerpo: m } = await api("/metricas");
    datos.metricas = m;
    contenedor.replaceChildren(...pintarCifras(m.accesibilidad || {}));
    tiemposTuberia(m);
    pintarModulos();
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
    pintarModulos();
  } catch {
    // Sin el dato, la fila queda con «—»: el enlace funciona igual
  }
}

pintarTuberia();
cuandoVisible(() => {
  actualizarSalud().then(programar);
  actualizarArchivo();
  actualizarDuplicados();
  cargarMuestra();
});
