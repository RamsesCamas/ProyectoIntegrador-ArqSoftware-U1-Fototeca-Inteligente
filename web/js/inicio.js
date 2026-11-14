// Inicio · «Resumen del archivo»: estado del sistema (GET /api/health), el archivo en cifras (GET /api/metricas), una
// muestra fija de 12 fotos reales del archivo (GET /api/fichas/{id}) y la tubería de las 7 capas con su p50 medido.
// Los nombres de los componentes vienen de la API: la web no conoce los recursos internos (R8).
// Carga: /health cada 30 s (cada 10 s solo mientras los modelos se precalientan o algo falla) y /metricas una vez;
// nada se pide con la pestaña oculta, y al volver se refresca /health si ya pasó su intervalo.
import { api, anunciar, el, insignia } from "./api.js";
import {
  CAPAS, ORDEN_CAPAS, SERIE_CAPA, claseSerie, crearMensaje, cuandoVisible, medidor, miniatura, numero, porcentaje, segundos,
  verFotoGuardada,
} from "./comun.js";
import { icono, ilustracion } from "./iconos.js";

const INTERVALO_S = 30;
const INTERVALO_ARRANQUE_S = 10;

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
  // El número de fotograma va impreso sobre la esquina de la foto, como en una hoja de contactos: el pie queda para el
  // titular completo (una línea; el texto entero en title y en el visor)
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

// ── Estado del sistema ──
/** «hace 45 s», «hace 12 min», «hace 3 h 5 min». */
function hace(segundosActivo) {
  const s = Math.max(0, Math.round(segundosActivo));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  const m = Math.floor((s % 3600) / 60);
  return `${Math.floor(s / 3600)} h${m ? ` ${m} min` : ""}`;
}

const plural = (n, uno, varios) => `${numero(n)} ${n === 1 ? uno : varios}`;
// Nombres de las filas que reporta el almacén (las demás se muestran tal cual)
const NOMBRE_FILAS = { documentos: ["documento", "documentos"], fichas: ["ficha", "fichas"], cache: ["entrada", "entradas"] };
// «Nombre (Tecnología)» → nombre corto en la celda y la tecnología junto a la insignia
const CON_TECNOLOGIA = /^(.+?)\s*\(([^)]+)\)\s*$/;

function partesNombre(c) {
  const m = CON_TECNOLOGIA.exec(c.nombre || "");
  return m ? { nombre: m[1], tecnologia: m[2] } : { nombre: c.nombre || "Componente", tecnologia: null };
}

function iconoComponente(clave, c) {
  if (clave === "servicio") return "servidor";
  if (clave === "almacen") return "archivo";
  if (clave === "cache") return "rayo";
  if (c.modelos_requeridos || /modelo/i.test(c.nombre || "")) return "cpu";
  if (c.colecciones || /vector/i.test(c.nombre || "")) return "base-datos";
  return "info";
}

/** Detalle de una línea de cada componente (el texto completo va en `title`). */
function detalle(c) {
  if (c.estado === "error") return c.error || "No disponible";
  if (c.modelos_requeridos) {
    const requeridos = c.modelos_requeridos.length;
    const faltan = (c.modelos_faltantes || []).length;
    return faltan ? `Faltan ${numero(faltan)} de ${numero(requeridos)} modelos`
      : `${numero((c.modelos_cargados || []).length)} de ${numero(requeridos)} modelos en memoria`;
  }
  if (c.colecciones) {
    const puntos = Object.values(c.colecciones);
    return puntos.length ? plural(puntos.reduce((s, n) => s + (n ?? 0), 0), "vector", "vectores") : "Sin colecciones todavía";
  }
  if (c.filas) {
    return Object.entries(c.filas).map(([t, n]) => (NOMBRE_FILAS[t] ? plural(n, ...NOMBRE_FILAS[t]) : `${t}: ${numero(n)}`)).join(" · ");
  }
  if (c.segundos_activo !== undefined) return `Activo desde hace ${hace(c.segundos_activo)}`;
  return c.descripcion || "";
}

/** Detalle completo para el `title`: descripción y, si hay colecciones, cuántos puntos tiene cada una. */
function detalleCompleto(c) {
  const colecciones = c.colecciones
    ? `${plural(Object.keys(c.colecciones).length, "colección", "colecciones")}: ${Object.entries(c.colecciones).map(([n, p]) => `${n} ${numero(p ?? 0)}`).join(" · ")}`
    : null;
  return [detalle(c), colecciones, c.descripcion].filter(Boolean).join(". ");
}

function celdaComponente(clave, c) {
  const { nombre, tecnologia } = partesNombre(c);
  const textoDetalle = detalle(c);
  return el("article", { clase: `tarjeta componente${c.estado === "error" ? " con-error" : ""}` },
    el("h3", { clase: "componente-nombre", title: c.nombre },
      icono(iconoComponente(clave, c)), el("span", { clase: "una-linea", texto: nombre })),
    el("p", { clase: "componente-estado" }, insignia(c.estado),
      tecnologia ? el("span", { clase: "componente-tecnologia una-linea", title: [tecnologia, c.version].filter(Boolean).join(" "), texto: tecnologia }) : null),
    el("p", { clase: "componente-detalle una-linea", title: detalleCompleto(c), texto: textoDetalle }));
}

let anterior = null;
let ultimaSalud = 0;
let temporizador = null;
let intervalo = INTERVALO_S;

async function actualizarSalud() {
  const contenedor = document.getElementById("componentes");
  const general = document.getElementById("estado-general");
  const precalentamiento = document.getElementById("precalentamiento");
  ultimaSalud = Date.now();
  try {
    const { cuerpo } = await api("/health", { aceptar: [503] });
    contenedor.replaceChildren(...Object.entries(cuerpo.componentes || {}).map(([clave, c]) => celdaComponente(clave, c)));
    contenedor.classList.remove("con-mensaje");
    general.replaceChildren(el("span", { clase: "solo-lectores", texto: "Estado general: " }), insignia(cuerpo.estado));
    document.getElementById("version-configuracion").replaceChildren("Configuración ",
      el("span", { clase: "mono", texto: cuerpo.versiones?.configuracion || "—" }));
    const pre = cuerpo.precalentamiento || {};
    precalentamiento.textContent =
      pre.estado === "en_curso" ? "Cargando los modelos en memoria…" :
      pre.estado === "listo" ? `Modelos listos en memoria (${numero(pre.segundos)} s)` :
      pre.estado === "error" ? "No se pudo cargar algún modelo" : "";
    if (anterior !== cuerpo.estado) anunciar(`Estado del sistema: ${cuerpo.estado === "ok" ? "en verde" : cuerpo.estado}`);
    anterior = cuerpo.estado;
    intervalo = cuerpo.estado === "ok" && pre.estado !== "en_curso" ? INTERVALO_S : INTERVALO_ARRANQUE_S;
  } catch (e) {
    general.replaceChildren(el("span", { clase: "solo-lectores", texto: "Estado general: " }), insignia("sin_conexion"));
    // Sin datos previos, la franja explica el problema; con datos, se conservan los últimos conocidos
    if (!contenedor.querySelector(".componente:not(.cargando)")) {
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
  return [
    cifra("foto", numero(a.fotos ?? 0), "fotos en el archivo"),
    cifra("check", numero(a.fichas_validadas ?? 0), "fichas validadas por el archivista"),
    // Más es mejor: el medidor no pasa a «aviso» al acercarse al total (aviso > 1)
    cifra("ojo", porcentaje(a.porcentaje_alt_validado), "de las fotos con texto alternativo validado",
      medidor(a.alt_validado ?? 0, a.fotos ?? 0, { aviso: 1.01, unidad: "" })),
    cifra("alerta", numero(a.requiere_revision ?? 0), "fichas por revisar",
      el("p", { clase: "cifra-nota", texto: `${plural(a.borrador ?? 0, "borrador", "borradores")} · ${numero(a.sin_ficha ?? 0)} sin ficha` })),
  ];
}

// ── Cómo se genera una ficha: las 7 capas, en el orden de comun.js, con su p50 medido ──
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
    return el("li", { clase: "etapa", "data-capa": clave },
      el("div", { clase: "etapa-cabeza", "aria-hidden": "true" }, icono(nombreIcono, "icono-24"),
        el("span", { clase: "etapa-numero" }, el("span", { clase: `muestra ${claseSerie(SERIE_CAPA[clave])}` }),
          String(i + 1).padStart(2, "0"))),
      el("h3", { texto: CAPAS[clave] || clave }),
      el("p", { clase: "etapa-texto", texto }),
      el("p", { clase: "etapa-tiempo", hidden: true }),
      i < ORDEN_CAPAS.length - 1 ? el("span", { clase: "etapa-flecha", "aria-hidden": "true" }, icono("chevron")) : null);
  }));
}

function tiemposTuberia(m) {
  const capas = m.latencia_por_capa?.fichas || {};
  for (const etapa of document.querySelectorAll("#tuberia .etapa")) {
    const p50 = capas[etapa.dataset.capa]?.p50_ms;
    if (typeof p50 !== "number") continue;
    const nodo = etapa.querySelector(".etapa-tiempo");
    nodo.replaceChildren(el("span", { clase: "solo-lectores", texto: "Tiempo típico: " }), "p50 ", el("span", { clase: "valor", texto: segundos(p50) }));
    nodo.hidden = false;
  }
  const total = capas.total;
  if (total && typeof total.p50_ms === "number") {
    const pie = document.getElementById("tuberia-total");
    const p95 = typeof total.p95_ms === "number" ? ` · p95 ${segundos(total.p95_ms)}` : "";
    pie.replaceChildren(icono("reloj"), el("span", { texto: "Tiempo total por ficha:" }),
      el("span", { clase: "mono", texto: `p50 ${segundos(total.p50_ms)}${p95}` }),
      total.n ? el("span", { clase: "suave", texto: `(${plural(total.n, "ficha medida", "fichas medidas")} en este equipo)` }) : null);
    pie.hidden = false;
    document.getElementById("tuberia-auxiliar").textContent = "Las 7 capas que recorre cada foto, con su tiempo típico (p50)";
  }
}

async function actualizarArchivo() {
  const contenedor = document.getElementById("cifras");
  try {
    const { cuerpo: m } = await api("/metricas");
    contenedor.replaceChildren(...pintarCifras(m.accesibilidad || {}));
    tiemposTuberia(m);
  } catch (e) {
    contenedor.replaceChildren(crearMensaje(e.message, "error"));
  } finally {
    contenedor.removeAttribute("aria-busy");
  }
}

pintarTuberia();
cuandoVisible(() => {
  actualizarSalud().then(programar);
  actualizarArchivo();
  cargarMuestra();
});
