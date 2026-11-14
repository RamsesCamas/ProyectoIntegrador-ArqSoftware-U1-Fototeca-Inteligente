// Catalogar: subir fotos → ficha (o lote) → revisar con fuentes → retroalimentación y validación.
import { api, anunciar, el, ETIQUETA_ESTADO, insignia } from "./api.js";
import {
  abrirVisor, CAPAS, claseSerie, duracion, mensaje, metadatosQuitados, miniatura, numero, ORDEN_CAPAS, pieTecnico, segundos,
  SERIE_CAPA, textoGuardrail, verFotoGuardada,
} from "./comun.js";

const ETIQUETAS_CAMPO = {
  titular: "Titular", texto_alternativo: "Texto alternativo", descripcion: "Descripción",
  descripcion_extendida: "Descripción extendida", palabras_clave: "Palabras clave",
};
const CAMPOS_TEXTO = ["titular", "texto_alternativo", "descripcion", "descripcion_extendida"];
const MAXIMOS = { titular: 120, texto_alternativo: 250, descripcion: 800, descripcion_extendida: 1200 };
const formularioCarga = document.getElementById("formulario-carga");
const botonCatalogar = document.getElementById("boton-catalogar");
const entradaFotos = document.getElementById("fotos");
const plegada = document.getElementById("carga-plegada");
const textoPlegada = document.getElementById("carga-plegada-texto");
const espera = document.getElementById("espera");
const progreso = document.getElementById("progreso");
const revision = document.getElementById("revision");
const seccionLote = document.getElementById("lote");
const OTRA_PESTANA = { target: "_blank", rel: "noopener" };
const EXTERNO = "enlace externo, requiere internet";
const vistaPrevia = document.getElementById("vista-previa");
const MAX_PREVIAS = 24;
const ANUNCIO_CADA_S = 20;   // lectores de pantalla: un aviso de progreso cada 20 s, no cada segundo
const movimientoReducido = window.matchMedia("(prefers-reduced-motion: reduce)");
let urlsPrevias = [];
let ocupado = false;

const tamano = (bytes) => (bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);
const puntajeTexto = (p) => (typeof p === "number" && Number.isFinite(p) ? ` · ${p.toFixed(2)}` : "");

/** Flecha visible ↗ y texto para lectores de pantalla en los enlaces que salen del sistema (sin red no abren). */
function marcaExterna(detalle = "") {
  return [el("span", { clase: "externo", "aria-hidden": "true", texto: "↗" }),
    el("span", { clase: "solo-lectores", texto: ` (${detalle}${EXTERNO}; se abre en otra pestaña)` })];
}

/**
 * Fuente de un campo como chip: foto similar (con miniatura; abre el visor con la foto y la ficha del ejemplo), regla,
 * término del tesauro (con su URI), archivista, descripción humana de referencia o etiqueta de Open Images.
 */
function chipFuente(f) {
  const puntaje = puntajeTexto(f.puntaje);
  if (f.tipo === "foto_similar") {
    return el("button", { type: "button", clase: "chip chip-foto",
      title: f.titulo ? `Foto similar: ${f.titulo} (ver en grande)` : `Foto similar ${f.id} (ver en grande)`,
      onclick: () => verFotoGuardada(f.id, { titulo: "Foto similar usada como ejemplo",
        extra: [["Puntaje de recuperación", typeof f.puntaje === "number" ? f.puntaje.toFixed(2) : f.puntaje]] }) },
      el("img", { src: `/api/fotos/${encodeURIComponent(f.id)}/miniatura?lado=96`, alt: "", width: "24", height: "24", decoding: "async" }),
      `Foto similar${puntaje}`,
      el("span", { clase: "solo-lectores", texto: `: ${f.titulo || f.id} (ver la foto y su ficha)` }));
  }
  if (f.tipo === "tesauro") {
    const texto = `Tesauro: ${f.titulo || f.id}${puntaje}`;
    return /^https?:/.test(f.id || "")
      ? el("a", { clase: "chip chip-tesauro", href: f.id, ...OTRA_PESTANA, title: `${f.id} (${EXTERNO})` }, texto,
        ...marcaExterna("término del Tesauro de la UNESCO; "))
      : el("span", { clase: "chip chip-tesauro", title: f.id }, texto);
  }
  if (f.tipo === "regla") {
    const texto = `Regla: ${f.titulo || f.id}${puntaje}`;
    // El extracto de la regla va en el título: se puede leer sin red, aunque el enlace a la norma no abra
    const titulo = f.extracto ? `${f.extracto}\n\nFragmento ${f.id}` : `Fragmento ${f.id}`;
    return f.url
      ? el("a", { clase: "chip chip-regla", href: f.url, ...OTRA_PESTANA, title: `${titulo}\n(${EXTERNO})` }, texto,
        ...marcaExterna(`fragmento ${f.id}; `))
      : el("span", { clase: "chip chip-regla", title: titulo }, texto, el("span", { clase: "solo-lectores", texto: ` (fragmento ${f.id})` }));
  }
  const texto = f.tipo === "archivista" ? "Corrección del archivista" : f.tipo === "referencia_humana" ? "Descripción humana de referencia"
    : f.tipo === "etiqueta_open_images" ? `Etiqueta: ${f.titulo || f.id}` : `${f.tipo}: ${f.id}`;
  return el("span", { clase: `chip chip-${f.tipo}`, title: f.titulo || f.id }, texto + puntaje);
}

function filaFuentes(id, fuentes, conSinFuente = true) {
  const lista = fuentes || [];
  return el("div", { clase: "fuentes", id },
    el("span", { clase: "fuentes-titulo", texto: "Fuentes:" }),
    lista.length ? lista.map(chipFuente) : conSinFuente ? el("span", { clase: "sin-fuente", texto: "Sin fuente verificable" }) : null);
}

function campoEditable(nombre, valor, fuentes, soloLectura) {
  const id = `campo-${nombre}`;
  const control = nombre === "titular"
    ? el("input", { id, name: nombre, type: "text", value: valor || "", maxlength: MAXIMOS[nombre], readonly: soloLectura })
    : el("textarea", { id, name: nombre, rows: nombre === "texto_alternativo" ? "3" : "4", maxlength: MAXIMOS[nombre], readonly: soloLectura }, valor || "");
  const contador = el("span", { clase: "contador", id: `${id}-contador` });
  const actualizar = () => { contador.textContent = `${control.value.length}/${MAXIMOS[nombre]} caracteres`; };
  control.addEventListener("input", actualizar);
  // Enter en el titular no debe enviar el formulario (el primer botón es «Validar ficha»)
  if (nombre === "titular") control.addEventListener("keydown", (ev) => { if (ev.key === "Enter") ev.preventDefault(); });
  control.setAttribute("aria-describedby", `${id}-contador ${id}-fuentes`);
  actualizar();
  return el("div", { clase: "campo" },
    el("label", { for: id, texto: ETIQUETAS_CAMPO[nombre] }), control, contador, filaFuentes(`${id}-fuentes`, fuentes));
}

function campoPalabras(palabras, fuentes, soloLectura) {
  const lista = el("ul", { clase: "palabras", id: "palabras-lista", "aria-label": "Palabras clave de la ficha" });
  const items = [...palabras];
  const entrada = soloLectura ? null : el("input", { id: "palabra-nueva", type: "text", maxlength: "80" });
  const pintar = () => lista.replaceChildren(...items.map((p, i) => el("li", { clase: `palabra palabra-${p.origen || "libre"}` },
    p.origen === "tesauro" && p.uri
      ? el("a", { href: p.uri, ...OTRA_PESTANA, title: `${p.uri} (${EXTERNO})` }, p.termino, " ", ...marcaExterna("término del tesauro; "))
      : p.termino,
    soloLectura ? null : el("button", { type: "button", clase: "quitar", "aria-label": `Quitar ${p.termino}`, onclick: () => {
      items.splice(i, 1); pintar(); anunciar(`Se quitó ${p.termino}`); entrada.focus();
    } }, "×"))));
  const agregar = () => {
    const t = entrada.value.trim();
    if (t) { items.push({ termino: t, origen: "libre" }); pintar(); entrada.value = ""; entrada.focus(); anunciar(`Se agregó ${t}`); }
  };
  entrada?.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); agregar(); } });
  pintar();
  return {
    nodo: el("div", { clase: "campo" }, el("p", { clase: "etiqueta", id: "palabras-titulo", texto: "Palabras clave" }), lista,
      soloLectura ? null : [el("label", { for: "palabra-nueva", clase: "solo-lectores", texto: "Agregar palabra clave" }),
        el("div", { clase: "fila" }, entrada, el("button", { type: "button", clase: "boton secundario", onclick: agregar }, "Agregar palabra"))],
      filaFuentes("campo-palabras_clave-fuentes", (fuentes || []).slice(0, 10), false)),
    items,
    reemplazar: (nuevas) => { items.splice(0, items.length, ...nuevas); pintar(); },
  };
}

function avisos(ficha, meta) {
  const nodos = [];
  if (meta?.duplicado_de) {
    const sim = meta.duplicado_de.similitud;
    nodos.push(el("div", { clase: "mensaje aviso", role: "status" },
      "Posible duplicado de ", el("a", { href: `catalogar.html?doc=${encodeURIComponent(meta.duplicado_de.documento_id)}`, texto: meta.duplicado_de.documento_id }),
      ` (similitud ${typeof sim === "number" ? sim.toFixed(2) : sim}). Se reutilizó su ficha: revísala antes de validarla.`));
  }
  if (ficha.advertencias?.length) {
    nodos.push(el("div", { clase: "mensaje aviso" }, el("p", { texto: "Advertencias:" }), el("ul", {}, ficha.advertencias.map((a) => el("li", { texto: a })))));
  }
  if (meta?.revision?.length) {
    nodos.push(el("div", { clase: "mensaje aviso" }, el("p", { texto: "Requiere revisión porque:" }), el("ul", {}, meta.revision.map((a) => el("li", { texto: a })))));
  }
  const activados = [...(meta?.guardrails?.entrada || []), ...(meta?.guardrails?.salida || [])].filter((g) => g.resultado !== "aprobada");
  if (activados.length) {
    nodos.push(el("div", { clase: "mensaje aviso" }, el("p", { texto: "Guardrails que actuaron:" }),
      el("ul", {}, activados.map((g) => el("li", { texto: textoGuardrail(g) })))));
  }
  return nodos;
}

/** Pliega el formulario de carga a una barra con «Catalogar otra foto» (la ficha queda arriba, a la vista). */
function plegarCarga(texto) {
  formularioCarga.hidden = true;
  plegada.hidden = false;
  textoPlegada.textContent = texto;
}

function desplegarCarga() {
  plegada.hidden = true;
  formularioCarga.hidden = false;
  formularioCarga.reset();
  mostrarElegidas([]);
  entradaFotos.focus();
}

function mostrarFicha(respuesta, { nombre = null } = {}) {
  const { documento_id: doc, ficha, fuentes = {}, meta = {} } = respuesta;
  let original = structuredClone(ficha);
  revision.hidden = false;
  // Sin traza (fichas del archivo inicial): solo lectura, sin «Tu opinión» ni validación
  const sinTraza = !meta.traza_id;
  const estadoFicha = el("span", {}, insignia(ficha.estado));
  const palabras = campoPalabras(ficha.palabras_clave || [], fuentes.palabras_clave, sinTraza);
  const destino = el("div", { id: "resultado-opinion", "aria-live": "polite" });
  const estadoUtil = { valor: null };
  let opinion = null;
  let acciones = null;
  if (!sinTraza) {
    const grupoUtil = el("div", { clase: "fila", role: "group", "aria-labelledby": "pregunta-util" });
    const botonUtil = (valor, texto) => el("button", { type: "button", clase: "boton secundario", "aria-pressed": "false",
      onclick: (ev) => {
        const pulsado = ev.currentTarget.getAttribute("aria-pressed") === "true";
        estadoUtil.valor = pulsado ? null : valor;
        grupoUtil.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
        if (!pulsado) ev.currentTarget.setAttribute("aria-pressed", "true");
      } }, texto);
    grupoUtil.append(botonUtil(true, "Útil"), botonUtil(false, "No útil"));
    opinion = el("fieldset", { clase: "opinion" }, el("legend", { texto: "Tu opinión" }),
      el("p", { id: "pregunta-util", clase: "etiqueta", texto: "¿Te fue útil la ficha?" }), grupoUtil,
      el("label", { for: "comentario", texto: "Comentario (opcional)" }),
      el("textarea", { id: "comentario", rows: "2", maxlength: "1000" }));
    acciones = el("div", { clase: "fila" },
      el("button", { type: "submit", clase: "boton", value: "validar", texto: "Validar ficha" }),
      el("button", { type: "submit", clase: "boton secundario", value: "opinar", texto: "Solo enviar opinión" }));
  }
  const formulario = el("form", { clase: "ficha", id: "formulario-ficha" },
    CAMPOS_TEXTO.map((c) => campoEditable(c, ficha[c], fuentes[c], sinTraza)),
    palabras.nodo, opinion, acciones, destino);
  formulario.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (sinTraza) return;
    const validar = ev.submitter?.value === "validar";
    const correcciones = {};
    for (const c of CAMPOS_TEXTO) {
      const v = formulario.querySelector(`[name=${c}]`).value.trim();
      if (v !== (original[c] || "").trim()) correcciones[c] = v;
    }
    const nuevas = palabras.items.map((p) => p.termino);
    if (JSON.stringify(nuevas) !== JSON.stringify((original.palabras_clave || []).map((p) => p.termino))) correcciones.palabras_clave = nuevas;
    const botones = formulario.querySelectorAll("button[type=submit]");
    botones.forEach((b) => { b.disabled = true; });
    try {
      const { cuerpo } = await api("/retroalimentacion", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ traza_id: meta.traza_id, util: estadoUtil.valor, comentario: document.getElementById("comentario").value.trim() || null,
          correcciones, validar_ficha: validar }) });
      let texto = "Opinión registrada. ¡Gracias!";
      if (cuerpo.ficha_validada && cuerpo.ficha) {
        original = structuredClone(cuerpo.ficha);
        for (const c of CAMPOS_TEXTO) {
          const control = formulario.querySelector(`[name=${c}]`);
          control.value = cuerpo.ficha[c] || "";
          control.dispatchEvent(new Event("input"));
        }
        palabras.reemplazar(cuerpo.ficha.palabras_clave || []);
        estadoFicha.replaceChildren(insignia("validada"));
        texto = "Ficha validada: ahora es un ejemplo más para catalogar fotos parecidas.";
      }
      mensaje(destino, `${texto} (traza ${cuerpo.traza_id})`, "ok");
      anunciar(texto);
    } catch (e) {
      mensaje(destino, e.message);
    } finally {
      botones.forEach((b) => { b.disabled = false; });
    }
  });
  // El visor muestra la copia guardada y la ficha tal como está guardada (se actualiza al validar)
  const verGuardada = () => verFotoGuardada(doc, { titulo: "Foto guardada en el archivo", ficha: original, enlaceFicha: false,
    extra: [["Ruta", meta.ruta], ["Metadatos quitados al guardar", metadatosQuitados(meta)]] });
  const titulo = el("h2", { id: "titulo-revision", tabindex: "-1", texto: sinTraza ? "Ficha guardada (solo lectura)" : "Revisa la ficha" });
  revision.replaceChildren(
    titulo,
    el("div", { clase: "revision" },
      el("figure", { clase: "foto" },
        el("button", { type: "button", clase: "boton-imagen", "aria-label": "Ver en grande la foto guardada y su ficha", onclick: verGuardada },
          el("img", { src: `/api/fotos/${encodeURIComponent(doc)}/miniatura`, width: "512", height: "384", decoding: "async",
            alt: ficha.texto_alternativo || `Foto ${doc} (sin texto alternativo todavía)` }),
          el("span", { clase: "lupa", "aria-hidden": "true", texto: "Ver en grande" })),
        el("figcaption", {}, `Documento ${doc} · Estado: `, estadoFicha)),
      el("div", {},
        sinTraza ? el("p", { clase: "mensaje info", texto: "Esta ficha es de solo lectura: viene del archivo inicial y no tiene traza, "
          + "así que no se puede calificar ni validar desde aquí." }) : null,
        ...avisos(ficha, meta), formulario)),
    pieTecnico(meta));
  plegarCarga(nombre ? `Ficha de «${nombre}».` : `Ficha del documento ${doc}.`);
  // Foco en el título (sin anillo) y la ficha arriba de la ventana
  titulo.focus({ preventScroll: true });
  titulo.scrollIntoView({ block: "start", behavior: movimientoReducido.matches ? "auto" : "smooth" });
  anunciar(`Ficha lista: ${ficha.titular || "sin titular"}`);
}

// ── Espera de una ficha (30–70 s en CPU) ──
let tiemposPromesa = null;
/** Latencias de las fichas registradas (GET /api/metricas → latencia_por_capa.fichas), una sola vez por página. */
function tiemposTipicos() {
  tiemposPromesa ||= api("/metricas").then(({ cuerpo }) => {
    const f = cuerpo?.latencia_por_capa?.fichas;
    return f?.total?.n ? f : null;
  }).catch(() => { tiemposPromesa = null; return null; });
  return tiemposPromesa;
}

function avisarAlSalir(ev) {
  ev.preventDefault();
  ev.returnValue = "";
}

function marcarOcupado(si) {
  ocupado = si;
  botonCatalogar.disabled = si;
  if (si) botonCatalogar.setAttribute("aria-busy", "true");
  else botonCatalogar.removeAttribute("aria-busy");
}

/**
 * Panel de espera: tiempo transcurrido, barra contra el p95 de las fichas registradas (marca en el p50) y la lista de
 * capas; al terminar, la lista se llena con los tiempos reales de meta.tiempos_por_capa_ms. No es una región viva:
 * los lectores de pantalla oyen un aviso cada 20 s (anunciar), no uno por segundo.
 */
function panelEspera(nombre) {
  const inicio = Date.now();
  const transcurrido = () => (Date.now() - inicio) / 1000;
  const titulo = el("h2", { id: "titulo-espera", tabindex: "-1", texto: nombre ? `Generando la ficha de «${nombre}»` : "Generando la ficha" });
  const reloj = el("p", { clase: "reloj", "aria-hidden": "true" });
  const relleno = el("span", { clase: "relleno" });
  const marca = el("span", { clase: "marca-p50" });
  const barra = el("div", { clase: "barra-tiempo", "aria-hidden": "true", hidden: true }, relleno, marca);
  const referencia = el("p", { texto: "Consultando cuánto suelen tardar las fichas…" });
  const subtitulo = el("h3", { texto: "Capas por las que pasa la foto" });
  const tiempos = {};
  const items = {};
  const lista = el("ol", { clase: "capas", role: "list" }, ORDEN_CAPAS.map((k) => {
    tiempos[k] = el("span", { clase: "capa-tiempo" });
    items[k] = el("li", {}, el("span", { clase: `muestra ${claseSerie(SERIE_CAPA[k])}`, "aria-hidden": "true" }),
      el("span", { clase: "capa-nombre", texto: CAPAS[k] }), tiempos[k]);
    return items[k];
  }));
  const nota = el("p", { clase: "nota-espera", texto: "La petición sigue en curso aunque no veas cambios: no recargues ni cierres la página." });
  const nodo = el("div", { clase: "espera" }, titulo, reloj, barra, referencia, subtitulo, lista, nota);
  let p50 = null;
  let p95 = null;
  let vigente = true;
  let siguienteAnuncio = ANUNCIO_CADA_S;
  const tic = () => {
    const s = transcurrido();
    reloj.replaceChildren(duracion(s), el("small", { texto: " transcurridos" }));
    if (p95) {
      relleno.style.width = `${Math.min(100, (s / p95) * 100).toFixed(1)}%`;
      if (s > p95 && !nodo.classList.contains("lenta")) {
        nodo.classList.add("lenta");
        nota.textContent = "Está tardando más que de costumbre, pero la petición sigue en curso: no recargues ni cierres la página.";
      }
    }
    if (s >= siguienteAnuncio) {
      siguienteAnuncio += ANUNCIO_CADA_S;
      anunciar(`Generando la ficha: ${duracion(s)} transcurridos${p50 ? `; suele tardar ${duracion(p50)}` : ""}.`);
    }
  };
  tic();
  const reloj1s = setInterval(tic, 1000);
  tiemposTipicos().then((f) => {
    if (!vigente) return;
    if (!f) {
      referencia.textContent = "Todavía no hay fichas registradas en las métricas para estimar la espera.";
      return;
    }
    p50 = f.total.p50_ms / 1000;
    p95 = f.total.p95_ms / 1000;
    referencia.textContent = `Según las ${numero(f.total.n)} fichas registradas, suele tardar ${duracion(p50)} (p50) `
      + `y el 95 % termina antes de ${duracion(p95)} (p95). La barra llega al final en el p95; la marca es el p50.`;
    marca.style.left = `${Math.min(100, (p50 / p95) * 100).toFixed(1)}%`;
    barra.hidden = false;
    subtitulo.textContent = "Capas por las que pasa la foto (p50 de cada una)";
    for (const k of ORDEN_CAPAS) if (f[k]?.n) tiempos[k].textContent = `p50 ${segundos(f[k].p50_ms)}`;
    tic();
  });
  return {
    nodo,
    enfocar: () => {
      titulo.focus({ preventScroll: true });
      nodo.scrollIntoView({ block: "nearest", behavior: movimientoReducido.matches ? "auto" : "smooth" });
    },
    terminar: (meta = {}) => {
      vigente = false;
      clearInterval(reloj1s);
      const total = typeof meta.tiempo_ms === "number" ? meta.tiempo_ms : transcurrido() * 1000;
      nodo.classList.remove("lenta");
      nodo.classList.add("terminada");
      titulo.textContent = `Ficha generada en ${segundos(total)}`;
      reloj.remove();
      nota.remove();
      if (p95) relleno.style.width = `${Math.min(100, (total / 1000 / p95) * 100).toFixed(1)}%`;
      referencia.textContent = [meta.ruta ? `Ruta: ${meta.ruta}.` : "", p50 ? `Lo típico es ${duracion(p50)} (p50) y ${duracion(p95)} (p95).` : ""]
        .filter(Boolean).join(" ");
      subtitulo.textContent = "Tiempo real de cada capa en esta ficha";
      const reales = meta.tiempos_por_capa_ms || {};
      for (const k of ORDEN_CAPAS) {
        const v = reales[k];
        const usada = typeof v === "number" && v > 0;
        items[k].classList.toggle("usada", usada);
        tiempos[k].textContent = usada ? segundos(v) : "no se usó";
      }
    },
    fallar: () => {
      vigente = false;
      clearInterval(reloj1s);
      nodo.remove();
    },
  };
}

/** POST /api/fichas con el panel de espera, el botón desactivado y el aviso al salir de la página. */
async function generarFicha(opciones, nombre) {
  if (ocupado) return;
  const panel = panelEspera(nombre);
  espera.replaceChildren(panel.nodo);
  progreso.replaceChildren();
  marcarOcupado(true);
  panel.enfocar();
  window.addEventListener("beforeunload", avisarAlSalir);
  try {
    const { cuerpo } = await api("/fichas", { method: "POST", ...opciones });
    panel.terminar(cuerpo.meta || {});
    mostrarFicha(cuerpo, { nombre });
  } catch (e) {
    panel.fallar();
    mensaje(progreso, e.message);
    const aviso = progreso.firstElementChild;
    if (aviso) { aviso.tabIndex = -1; aviso.focus(); }
  } finally {
    window.removeEventListener("beforeunload", avisarAlSalir);
    marcarOcupado(false);
  }
}

async function catalogarLote(archivos) {
  if (ocupado) return;
  const datos = new FormData();
  datos.append("tipo", "foto");
  for (const a of archivos) datos.append("archivos", a);
  espera.replaceChildren();
  marcarOcupado(true);
  mensaje(progreso, `Subiendo ${archivos.length} fotos…`, "info");
  anunciar(`Subiendo ${archivos.length} fotos…`);
  try {
    const { cuerpo: carga } = await api("/documentos", { method: "POST", body: datos });
    const ids = [...new Set(carga.documentos.filter((d) => !d.error).map((d) => d.documento_id))];
    const rechazados = carga.documentos.filter((d) => d.error);
    const nota = rechazados.length ? el("p", { clase: "mensaje error", role: "alert",
      texto: `${rechazados.length} archivos rechazados: ${rechazados.map((d) => `${d.nombre} (${d.error.mensaje})`).join("; ")}` }) : "";
    const { cuerpo: lote } = await api("/lotes", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ documento_ids: ids }) });
    const barra = el("progress", { max: String(lote.total), value: "0", id: "barra-lote", "aria-label": "Progreso del lote" });
    const texto = el("p", { role: "status" });
    const errores = el("div");
    // El progreso vive dentro de la sección del lote: catalogar otra foto mientras tanto no lo borra
    progreso.replaceChildren();
    document.getElementById("lote-progreso").replaceChildren(barra, texto, nota, errores);
    const lista = document.getElementById("lista-lote");
    lista.replaceChildren();
    seccionLote.hidden = false;
    let pintadas = 0;
    const consultar = async () => {
      try {
        const { cuerpo: estado } = await api(`/lotes/${encodeURIComponent(lote.lote_id)}`);
        barra.value = estado.completadas + estado.fallidas;
        texto.textContent = `${estado.completadas} de ${estado.total} fichas listas${estado.fallidas ? ` · ${estado.fallidas} fallidas` : ""}`;
        errores.replaceChildren(...(estado.errores || []).map((e) => el("p", { clase: "mensaje error", texto: `${e.documento_id}: ${e.mensaje}` })));
        // Solo se agregan las tarjetas nuevas: las ya pintadas no se vuelven a pedir ni pierden el foco
        lista.append(...(estado.fichas || []).slice(pintadas).map((f, i) => el("button", { type: "button", clase: "tarjeta tarjeta-boton",
          onclick: () => mostrarFicha(f) },
          miniatura(f.documento_id, { alt: f.ficha.texto_alternativo || `Foto ${f.documento_id}`, diferida: pintadas + i >= 4 }),
          el("strong", { texto: f.ficha.titular || f.documento_id }),
          el("span", { texto: `Estado: ${ETIQUETA_ESTADO[f.ficha.estado] || f.ficha.estado} · revisar` }))));
        pintadas = (estado.fichas || []).length;
        if (estado.estado !== "terminado") setTimeout(consultar, 3000);
        else anunciar(`El lote terminó: ${estado.completadas} fichas listas${estado.fallidas ? `, ${estado.fallidas} fallidas` : ""}.`);
      } catch (e) { mensaje(errores, e.message); }
    };
    consultar();
  } catch (e) {
    mensaje(progreso, e.message);
  } finally {
    marcarOcupado(false);
  }
}

/** Vista previa de las fotos elegidas, antes de subirlas: se ven tal como están en tu equipo. */
function mostrarElegidas(archivos) {
  urlsPrevias.forEach((u) => URL.revokeObjectURL(u));
  const imagenes = archivos.filter((a) => /^image\/(jpeg|png)$/.test(a.type));
  const visibles = imagenes.slice(0, MAX_PREVIAS);
  urlsPrevias = visibles.map((a) => URL.createObjectURL(a));
  vistaPrevia.hidden = !visibles.length;
  const items = visibles.map((a, i) => {
    const url = urlsPrevias[i];
    const medidas = el("span", {});
    const img = el("img", { src: url, alt: `Vista previa de ${a.name}`, decoding: "async" });
    const datos = () => [["Archivo", a.name], ["Tamaño", tamano(a.size)], ["Tipo", a.type],
      ["Medidas originales", img.naturalWidth ? `${img.naturalWidth} × ${img.naturalHeight} px` : null],
      ["Al guardarla", "El servicio quita el GPS, el número de serie de la cámara y los datos del autor antes de guardarla."]];
    img.addEventListener("load", () => { medidas.textContent = ` · ${img.naturalWidth} × ${img.naturalHeight} px`; });
    return el("li", {},
      el("button", { type: "button", clase: "boton-imagen", "aria-label": `Ver en grande ${a.name}`,
        onclick: () => abrirVisor({ src: url, alt: `Foto elegida: ${a.name}`, titulo: `Foto elegida: ${a.name}`, datos: datos(),
          nota: "Es el archivo original, todavía en tu equipo: aún no se ha subido." }) },
        img, el("span", { clase: "lupa", "aria-hidden": "true", texto: "Ver" })),
      el("span", { clase: "nombre-archivo", texto: a.name }),
      el("span", { clase: "id" }, tamano(a.size), medidas));
  });
  if (imagenes.length > visibles.length) items.push(el("li", { clase: "id", texto: `y ${imagenes.length - visibles.length} fotos más` }));
  vistaPrevia.replaceChildren(...items);
  if (imagenes.length === 1) tiemposTipicos();   // se adelanta la consulta del tiempo típico para la espera
  if (imagenes.length) anunciar(imagenes.length === 1 ? "1 foto elegida: puedes verla antes de catalogar" : `${imagenes.length} fotos elegidas`);
}

entradaFotos.addEventListener("change", (ev) => mostrarElegidas([...ev.target.files]));
document.getElementById("otra-foto").addEventListener("click", desplegarCarga);

formularioCarga.addEventListener("submit", (ev) => {
  ev.preventDefault();
  if (ocupado) return;   // un solo POST a la vez, aunque se pulse Enter o el botón dos veces
  const archivos = [...entradaFotos.files];
  if (!archivos.length) return;
  revision.hidden = true;
  if (archivos.length === 1) {
    const datos = new FormData();
    datos.append("foto", archivos[0]);
    generarFicha({ body: datos }, archivos[0].name);
  } else {
    seccionLote.hidden = true;
    catalogarLote(archivos);
  }
});

const zona = document.getElementById("zona-soltar");
zona.addEventListener("dragover", (e) => { e.preventDefault(); zona.classList.add("activa"); });
zona.addEventListener("dragleave", () => zona.classList.remove("activa"));
zona.addEventListener("drop", (e) => {
  e.preventDefault();
  zona.classList.remove("activa");
  entradaFotos.files = e.dataTransfer.files;
  mostrarElegidas([...e.dataTransfer.files]);
});

// catalogar.html?doc=ID → muestra la ficha guardada (o la genera si la foto todavía no tiene)
const doc = new URLSearchParams(location.search).get("doc");
if (doc) {
  (async () => {
    try {
      const { cuerpo } = await api(`/fichas/${encodeURIComponent(doc)}`, { aceptar: [404] });
      if (cuerpo?.ficha) {
        mostrarFicha({ documento_id: doc, ficha: cuerpo.ficha, fuentes: cuerpo.fuentes,
          meta: { traza_id: cuerpo.traza_id, ruta: `guardada (${cuerpo.origen})`, cache: "ninguna", modelos: {}, tiempos_por_capa_ms: {} } });
      } else {
        await generarFicha({ headers: { "Content-Type": "application/json" }, body: JSON.stringify({ documento_id: doc }) }, null);
      }
    } catch (e) { mensaje(progreso, e.message); }
  })();
}
