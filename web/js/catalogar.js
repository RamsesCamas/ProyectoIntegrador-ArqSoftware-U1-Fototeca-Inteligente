// Catalogar: subir fotos → espera informativa → ficha IPTC como Inspector (fuentes por campo) → opinión y validación.
// Con varias fotos, un lote con su progreso. catalogar.html?doc=ID abre la ficha guardada como página propia (migas
// «Archivo › id», h1 con el titular) o la genera si la foto todavía no tiene.
import { api, anunciar, el, insignia } from "./api.js";
import {
  abrirVisor, CAPAS, crearMensaje, fuente, leyendaFuentes, mensaje, metadatosQuitados, miniatura, numero, ORDEN_CAPAS,
  pieTecnico, segundos, textoGuardrail, verFotoGuardada,
} from "./comun.js";
import { icono } from "./iconos.js";

const ETIQUETAS_CAMPO = {
  titular: "Titular", texto_alternativo: "Texto alternativo", descripcion: "Descripción",
  descripcion_extendida: "Descripción extendida", palabras_clave: "Palabras clave",
};
const CAMPOS_TEXTO = ["titular", "texto_alternativo", "descripcion", "descripcion_extendida"];
const MAXIMOS = { titular: 120, texto_alternativo: 250, descripcion: 800, descripcion_extendida: 1200 };
const AVISO_ALT = 225;   // el texto alternativo pasa a ámbar desde aquí (y a rojo por encima de 250)
const FILAS = { texto_alternativo: "3", descripcion: "4", descripcion_extendida: "4" };
/** Icono de cada capa de la tubería (el mismo que en Inicio y Métricas). */
const ICONO_CAPA = {
  guardrails_entrada: "escudo", cache: "rayo", contexto: "libros", enrutador: "bifurcacion",
  modelo_vision: "ojo", modelo_composicion: "pluma", guardrails_salida: "escudo-check",
};
const RUTAS = { rapida: "ruta rápida", completa: "ruta completa", cache: "desde la caché" };
const NOTA_SOLO_LECTURA = "Ficha del archivo inicial, sin traza: se puede consultar, pero no calificar ni validar desde aquí.";
const SIN_CONTENIDO = "Sin contenido";
const OTRA_PESTANA = { target: "_blank", rel: "noopener" };
const EXTERNO = "enlace externo, requiere internet";
const MAX_PREVIAS = 24;
const ANUNCIO_CADA_S = 20;   // lectores de pantalla: un aviso de progreso cada 20 s, no cada segundo
const movimientoReducido = window.matchMedia("(prefers-reduced-motion: reduce)");

const $ = (id) => document.getElementById(id);
const formularioCarga = $("formulario-carga");
const botonCatalogar = $("boton-catalogar");
const textoBoton = $("boton-catalogar-texto");
const etiquetaElegir = document.querySelector(".elegir label");
const textoElegir = $("texto-elegir");
const estadoCarga = $("estado-carga");
const entradaFotos = $("fotos");
const zona = $("zona-soltar");
const elegidas = $("elegidas");
const tituloElegidas = $("titulo-elegidas");
const vistaPrevia = $("vista-previa");
const espera = $("espera");
const progreso = $("progreso");
const revision = $("revision");
const seccionLote = $("lote");
const loteResumen = $("lote-resumen");
const loteProgreso = $("lote-progreso");
const listaLote = $("lista-lote");
let urlsPrevias = [];
let ocupado = false;

const tamano = (bytes) => (bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);
const plural = (n, uno, varios) => `${numero(n)} ${n === 1 ? uno : varios}`;
const enc = encodeURIComponent;
const vacio = (v) => !String(v ?? "").trim();
/** Tiempo de reloj en m:ss (h:mm:ss si pasa de una hora). */
function reloj(s) {
  const t = Math.max(0, Math.round(s));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const ss = String(t % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}
const desplazar = (nodo) => nodo.scrollIntoView({ block: "start", behavior: movimientoReducido.matches ? "auto" : "smooth" });
const insigniaSoloLectura = () => el("span", { clase: "insignia neutra" }, icono("ojo"), "Solo lectura");

// ── Fuentes de cada campo (trazabilidad): un solo nombre por tipo, el de la leyenda ──
const puntajeChip = (p) => (typeof p === "number" && Number.isFinite(p) ? el("span", { clase: "puntaje-chip", texto: p.toFixed(2) }) : null);
const claseDe = (tipo) => `chip ${fuente(tipo).claseChip || `chip-${tipo}`}`;

/**
 * Fuente de un campo como chip, con el icono, el color y el nombre de su tipo (los mismos de la leyenda) y el detalle
 * solo si aporta: la regla concreta, el término del tesauro o la etiqueta. Una foto similar lleva su miniatura y abre el
 * visor con la foto y la ficha del ejemplo; la regla lleva su extracto en el título (legible sin red).
 */
function chipFuente(f) {
  const tipo = fuente(f.tipo);
  const clase = claseDe(f.tipo);
  const puntaje = puntajeChip(f.puntaje);
  const detalle = f.titulo || f.id;
  if (f.tipo === "foto_similar") {
    return el("button", { type: "button", clase, title: `${tipo.etiqueta}: ${detalle} (ver en grande)`,
      onclick: () => verFotoGuardada(f.id, { titulo: "Foto similar usada como ejemplo",
        extra: [["Puntaje de recuperación", typeof f.puntaje === "number" ? f.puntaje.toFixed(2) : f.puntaje]] }) },
      el("img", { src: `/api/fotos/${enc(f.id)}/miniatura?lado=96`, alt: "", width: "24", height: "24", decoding: "async" }),
      tipo.etiqueta, puntaje, el("span", { clase: "solo-lectores", texto: `: ${detalle} (ver la foto y su ficha)` }));
  }
  if (f.tipo === "regla") {
    const titulo = f.extracto ? `${f.extracto}\n\nFragmento ${f.id}` : `Fragmento ${f.id}`;
    return f.url
      ? el("a", { clase, href: f.url, ...OTRA_PESTANA, title: `${titulo}\n(${EXTERNO})` }, icono(tipo.icono), `${tipo.etiqueta}: ${detalle}`, puntaje,
        el("span", { clase: "externo", "aria-hidden": "true", texto: "↗" }),
        el("span", { clase: "solo-lectores", texto: ` (fragmento ${f.id}; ${EXTERNO}; se abre en otra pestaña)` }))
      : el("span", { clase, title: titulo }, icono(tipo.icono), `${tipo.etiqueta}: ${detalle}`, puntaje,
        el("span", { clase: "solo-lectores", texto: ` (fragmento ${f.id})` }));
  }
  // Referencia humana y archivista: el tipo basta (el detalle, p. ej. el corpus y su licencia, va en el título)
  const texto = f.tipo === "referencia_humana" || f.tipo === "archivista" ? tipo.etiqueta : `${tipo.etiqueta}: ${detalle}`;
  return el("span", { clase, title: detalle }, icono(tipo.icono), texto, puntaje);
}

const sinFuente = () => el("span", { clase: "sin-fuente" }, icono("alerta"), "Sin fuente verificable");
/** Un campo vacío no necesita fuente: se dice en gris, sin aviso (y no cuenta en «Procedencia»). */
const noAplica = () => el("span", { clase: "sin-fuente campo-vacio", texto: "no aplica (sin contenido)" });

function filaFuentes(id, fuentes, estaVacio) {
  const lista = fuentes || [];
  return el("div", { clase: "fuentes", id },
    el("span", { clase: "fuentes-titulo", texto: "Fuentes:" }), lista.length ? lista.map(chipFuente) : estaVacio ? noAplica() : sinFuente());
}

/** Panel «Procedencia de la ficha»: leyenda de los tipos con sus citas y los campos CON texto que no citan fuente. */
function panelProcedencia(ficha, fuentes) {
  const conteos = {};
  const sinCitas = [];
  for (const c of [...CAMPOS_TEXTO, "palabras_clave"]) {
    const lista = fuentes[c] || [];
    const conTexto = c === "palabras_clave" ? (ficha.palabras_clave || []).length > 0 : !vacio(ficha[c]);
    if (conTexto && !lista.length) sinCitas.push(ETIQUETAS_CAMPO[c]);
    for (const f of lista) conteos[f.tipo] = (conteos[f.tipo] || 0) + 1;
  }
  const total = Object.values(conteos).reduce((a, b) => a + b, 0);
  return el("section", { clase: "panel procedencia", "aria-labelledby": "titulo-procedencia" },
    el("header", { clase: "panel-cabecera" }, icono("tesauro"), el("h3", { id: "titulo-procedencia", texto: "Procedencia de la ficha" }),
      el("p", { clase: "panel-auxiliar", texto: plural(total, "cita", "citas") })),
    el("div", { clase: "panel-cuerpo" },
      total ? leyendaFuentes(conteos) : el("p", { clase: "suave", texto: "Ningún campo cita una fuente todavía." }),
      sinCitas.length
        ? el("p", { clase: "procedencia-campos" }, el("span", { clase: "sin-fuente" }, icono("alerta"), "Sin fuente verificable:"),
          el("span", { texto: sinCitas.join(", ") }))
        : el("p", { clase: "procedencia-campos completa" }, icono("check"),
          el("span", { texto: "Todos los campos con contenido citan una fuente." }))));
}

// ── Campos de la ficha ──
/**
 * Un campo: etiqueta con su contador en mono a la derecha, el control (en edición) o el texto plano (en solo lectura) y
 * su fila «Fuentes:». El texto alternativo lleva además una barra neutra: ámbar desde 225 y roja por encima de 250.
 */
function campoTexto(nombre, valor, fuentes, soloLectura) {
  const id = `campo-${nombre}`;
  const idContador = `${id}-contador`;
  const max = MAXIMOS[nombre];
  const estaVacio = vacio(valor);
  const contador = el("span", { clase: "contador", id: idContador });
  const etiqueta = soloLectura ? el("span", { clase: "etiqueta", id: `${id}-etiqueta`, texto: ETIQUETAS_CAMPO[nombre] })
    : el("label", { for: id, texto: ETIQUETAS_CAMPO[nombre] });
  let control;
  if (soloLectura) {
    control = el("p", { id, clase: `valor-ficha${estaVacio ? " sin-contenido" : ""}`, "aria-labelledby": `${id}-etiqueta`,
      "aria-describedby": `${idContador} ${id}-fuentes` }, estaVacio ? SIN_CONTENIDO : valor);
  } else {
    control = nombre === "titular"
      ? el("input", { id, name: nombre, type: "text", value: valor || "", maxlength: max, placeholder: SIN_CONTENIDO, autocomplete: "off" })
      : el("textarea", { id, name: nombre, rows: FILAS[nombre], maxlength: max, placeholder: SIN_CONTENIDO }, valor || "");
    control.setAttribute("aria-describedby", `${idContador} ${id}-fuentes`);
  }
  const relleno = nombre === "texto_alternativo" ? el("span", { clase: "barra-limite-relleno" }) : null;
  const barra = relleno ? el("div", { clase: "barra-limite", "aria-hidden": "true" }, relleno) : null;
  const actualizar = () => {
    const n = soloLectura ? (valor || "").length : control.value.length;
    const nivel = n > max ? "error" : barra && n >= AVISO_ALT ? "aviso" : "ok";
    contador.dataset.nivel = nivel;
    contador.replaceChildren(`${n}/${max}`, el("span", { clase: "solo-lectores", texto: " caracteres" }), n > max ? " · Excede" : "");
    if (barra) {
      barra.dataset.nivel = nivel;
      relleno.style.width = `${Math.min(100, (n / max) * 100).toFixed(1)}%`;
    }
  };
  if (!soloLectura) {
    control.addEventListener("input", actualizar);
    // Enter en el titular no envía el formulario (el primer botón de envío es «Validar ficha»)
    if (nombre === "titular") control.addEventListener("keydown", (ev) => { if (ev.key === "Enter") ev.preventDefault(); });
  }
  actualizar();
  return el("div", { clase: "campo campo-ficha" }, el("div", { clase: "campo-cabecera" }, etiqueta, contador),
    control, barra, filaFuentes(`${id}-fuentes`, fuentes, estaVacio));
}

/**
 * Qué fuente respalda cada palabra: su término del Tesauro de la UNESCO (con su puntaje) y, en las fichas del archivo
 * inicial, la etiqueta de Open Images de la que salió (la fuente que la precede en la lista). Lo que no se puede
 * asignar a una palabra (p. ej. las fotos similares) queda en una fila «Para todas las palabras».
 */
function origenPalabras(items, fuentes) {
  const usadas = new Set();
  const filas = items.map((p) => {
    const i = fuentes.findIndex((f, j) => !usadas.has(j) && f.tipo === "tesauro" && ((p.uri && f.id === p.uri) || f.titulo === p.termino));
    if (i >= 0) usadas.add(i);
    const k = i > 0 && fuentes[i - 1].tipo === "etiqueta_open_images" && !usadas.has(i - 1) ? i - 1 : -1;
    if (k >= 0) usadas.add(k);
    return { p, tesauro: i >= 0 ? fuentes[i] : null, etiqueta: k >= 0 ? fuentes[k] : null };
  });
  const conEtiqueta = filas.some((f) => f.etiqueta);
  const resto = fuentes.filter((_, j) => !usadas.has(j));
  const celdaTesauro = (f) => el("span", { clase: "celda-fuente" },
    el("span", { clase: claseDe("tesauro"), title: f.id }, icono(fuente("tesauro").icono), f.titulo || f.id, puntajeChip(f.puntaje)),
    /^https?:/.test(f.id || "") ? el("a", { clase: "enlace-externo", href: f.id, ...OTRA_PESTANA, title: `${f.id} (${EXTERNO})`,
      "aria-label": `${f.titulo || f.id} en el Tesauro de la UNESCO (${EXTERNO}; se abre en otra pestaña)` }, icono("externo")) : null);
  const nodos = [];
  if (filas.length) {
    nodos.push(el("div", { clase: "desplazable tabla-palabras-envoltura" }, el("table", { clase: "tabla tabla-compacta tabla-palabras" },
      el("caption", { clase: "solo-lectores", texto: "Fuente de cada palabra clave" }),
      el("thead", {}, el("tr", {}, el("th", { scope: "col", texto: "Palabra" }), el("th", { scope: "col", texto: fuente("tesauro").etiqueta }),
        conEtiqueta ? el("th", { scope: "col", texto: fuente("etiqueta_open_images").etiqueta }) : null)),
      el("tbody", {}, filas.map(({ p, tesauro, etiqueta }) => el("tr", {},
        el("th", { scope: "row", texto: p.termino }),
        el("td", {}, tesauro ? celdaTesauro(tesauro) : el("span", { clase: "suave", texto: "Término libre" })),
        conEtiqueta ? el("td", {}, etiqueta
          ? el("span", { clase: claseDe("etiqueta_open_images"), title: etiqueta.id }, icono(fuente("etiqueta_open_images").icono), etiqueta.titulo || etiqueta.id)
          : el("span", { clase: "suave", texto: "—" })) : null))))));
  }
  if (resto.length || !filas.length) {
    nodos.push(el("div", { clase: "fuentes" }, el("span", { clase: "fuentes-titulo", texto: filas.length ? "Para todas las palabras:" : "Fuentes:" }),
      resto.length ? resto.map(chipFuente) : noAplica()));
  }
  return nodos;
}

function campoPalabras(palabras, fuentes, soloLectura) {
  const lista = el("ul", { clase: "etiquetas-clave", id: "palabras-lista", "aria-labelledby": "palabras-titulo" });
  const items = [...palabras];
  const todas = fuentes || [];
  const origen = el("div", { clase: "fuentes-palabras", id: "campo-palabras_clave-fuentes" });
  const entrada = soloLectura ? null : el("input", { id: "palabra-nueva", type: "text", maxlength: "80", placeholder: "Nueva palabra clave",
    autocomplete: "off" });
  // Las palabras son chips cuadrados de texto (sin enlace): su término del tesauro, con su enlace, va en la tabla de abajo
  const pintar = () => {
    lista.replaceChildren(...(items.length ? items.map((p, i) => el("li", { clase: "etiqueta-clave" }, p.termino,
      soloLectura ? null : el("button", { type: "button", clase: "quitar", "aria-label": `Quitar ${p.termino}`, onclick: () => {
        items.splice(i, 1); pintar(); anunciar(`Se quitó ${p.termino}`); entrada.focus();
      } }, icono("cerrar"))))
      : [el("li", { clase: "valor-ficha sin-contenido", texto: SIN_CONTENIDO })]));
    origen.replaceChildren(...origenPalabras(items, todas));
  };
  const agregar = () => {
    const t = entrada.value.trim();
    if (!t) { entrada.focus(); return; }
    if (items.some((p) => p.termino.toLocaleLowerCase("es") === t.toLocaleLowerCase("es"))) {
      anunciar(`${t} ya está en la ficha`);
      entrada.select();
      return;
    }
    items.push({ termino: t, origen: "libre" });
    pintar();
    entrada.value = "";
    entrada.focus();
    anunciar(`Se agregó ${t}`);
  };
  entrada?.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); agregar(); } });
  pintar();
  return {
    nodo: el("div", { clase: "campo campo-ficha" }, lista,
      soloLectura ? null : [el("label", { for: "palabra-nueva", clase: "solo-lectores", texto: "Agregar palabra clave" }),
        el("div", { clase: "fila agregar-palabra" }, entrada,
          el("button", { type: "button", clase: "boton secundario", onclick: agregar }, icono("mas"), "Agregar"))],
      origen),
    items,
    reemplazar: (nuevas) => { items.splice(0, items.length, ...nuevas); pintar(); },
  };
}

/** Sección del inspector con su sobretítulo (14 px, seminegrita, gris, con regla encima). */
const seccion = (id, titulo, ...hijos) => el("div", { clase: "seccion", role: "group", "aria-labelledby": id },
  el("h4", { id, clase: "seccion-titulo", texto: titulo }), ...hijos);

/** Avisos de la ficha: posible duplicado, advertencias del modelo, motivos de revisión y guardrails que actuaron. */
function avisos(ficha, meta) {
  const nodos = [];
  if (meta?.duplicado_de) {
    const sim = meta.duplicado_de.similitud;
    nodos.push(crearMensaje(["Posible duplicado de ",
      el("a", { href: `catalogar.html?doc=${enc(meta.duplicado_de.documento_id)}`, clase: "id", texto: meta.duplicado_de.documento_id }),
      ` (similitud ${typeof sim === "number" ? sim.toFixed(2) : sim}). Se reutilizó su ficha: revísala antes de validarla.`], "aviso"));
  }
  const grupos = [];
  if (ficha.advertencias?.length) grupos.push(["Advertencias:", ficha.advertencias]);
  if (meta?.revision?.length) grupos.push(["Requiere revisión porque:", meta.revision]);
  const activados = [...(meta?.guardrails?.entrada || []), ...(meta?.guardrails?.salida || [])].filter((g) => g.resultado !== "aprobada");
  if (activados.length) grupos.push(["Guardrails que actuaron:", activados.map(textoGuardrail)]);
  if (grupos.length) {
    const m = crearMensaje(grupos.map(([titulo, lista]) => el("div", { clase: "aviso-grupo" },
      el("p", { clase: "aviso-titulo", texto: titulo }), el("ul", {}, lista.map((t) => el("li", { texto: t }))))), "aviso");
    m.removeAttribute("role");   // se lee con la ficha; el aviso vivo es «Ficha lista»
    nodos.push(m);
  }
  return nodos;
}

/** Las 7 capas con su icono y un valor por capa (p50 típico o tiempo real); devuelve la lista y sus celdas de valor. */
function listaCapas() {
  const valores = {};
  const items = {};
  const lista = el("ol", { clase: "capas", role: "list" }, ORDEN_CAPAS.map((k) => {
    valores[k] = el("span", { clase: "capa-tiempo" });
    items[k] = el("li", { clase: "capa" }, icono(ICONO_CAPA[k]), el("span", { clase: "capa-nombre", texto: CAPAS[k] }), valores[k]);
    return items[k];
  }));
  return { lista, valores, items };
}

/**
 * Resumen de la generación en una línea («Generada en 10.2 s · ruta rápida»). Si la respuesta trae los tiempos por capa,
 * es un botón que despliega la lista con el tiempo real de cada capa (el pie técnico tiene además la barra apilada).
 */
function resumenGeneracion(meta) {
  const partes = [];
  if (typeof meta.tiempo_ms === "number") partes.push(`Generada en ${segundos(meta.tiempo_ms)}`);
  const cache = meta.cache === "exacta" ? "caché exacta" : meta.cache === "semantica" ? "caché semántica" : null;
  const ruta = cache || RUTAS[meta.ruta];
  if (ruta) partes.push(ruta);
  if (!partes.length) return { control: null, region: null };
  const texto = partes.join(" · ");
  const reales = meta.tiempos_por_capa_ms || {};
  if (!ORDEN_CAPAS.some((k) => typeof reales[k] === "number")) {
    return { control: el("p", { clase: "generacion" }, icono("reloj"), texto), region: null };
  }
  const { lista, valores, items } = listaCapas();
  for (const k of ORDEN_CAPAS) {
    const v = reales[k];
    const usada = typeof v === "number" && v > 0;
    items[k].classList.add(usada ? "usada" : "no-usada");
    valores[k].textContent = usada ? segundos(v) : "no se usó";
  }
  const region = el("div", { clase: "tiempos-ficha", id: "tiempos-ficha", hidden: true },
    el("h3", { texto: "Tiempo real de cada capa en esta ficha" }), lista);
  const control = el("button", { type: "button", clase: "generacion boton-enlace", "aria-expanded": "false", "aria-controls": "tiempos-ficha",
    onclick: (ev) => {
      const abierto = ev.currentTarget.getAttribute("aria-expanded") === "true";
      ev.currentTarget.setAttribute("aria-expanded", String(!abierto));
      region.hidden = abierto;
    } }, icono("reloj"), el("span", { texto }), el("span", { clase: "generacion-accion" }, "Tiempos por capa", icono("chevron", "generacion-chevron")));
  return { control, region };
}

// ── Carga: plegar y desplegar ──
let botonOtraFoto = null;
function plegarCarga() {
  formularioCarga.hidden = true;
}

function desplegarCarga() {
  espera.replaceChildren();
  progreso.replaceChildren();
  formularioCarga.hidden = false;
  formularioCarga.reset();
  mostrarElegidas([]);
  if (botonOtraFoto) botonOtraFoto.hidden = true;   // el formulario ya está a la vista
  entradaFotos.focus({ preventScroll: true });
  desplazar(formularioCarga);
}

// ── Encabezado de la ficha guardada (catalogar.html?doc=ID): la página es la ficha ──
function migas(doc) {
  return el("nav", { clase: "migas", "aria-label": "Ruta de navegación" }, el("ol", {},
    el("li", {}, el("a", { href: "archivo.html", texto: "Archivo" })),
    el("li", {}, el("span", { clase: "id", "aria-current": "page", texto: doc }))));
}

/** Módulo activo de origen (Archivo) en la navegación. */
function marcarArchivoActivo() {
  for (const a of document.querySelectorAll("nav.navegacion a")) {
    if (a.getAttribute("href") === "archivo.html") a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
}

/** Mientras carga: migas y h1 provisional (sin id: la ficha aún no está lista). */
function encabezadoProvisional(doc) {
  const texto = document.querySelector(".encabezado-pagina .encabezado-texto");
  if (!texto) return;
  texto.replaceChildren(migas(doc), el("h1", { texto: `Ficha ${doc}` }));
  marcarArchivoActivo();
}

/** Encabezado de página de la ficha: migas, h1 con el titular, estado, «Solo lectura» con su nota y la acción. */
function encabezadoDeFicha(doc, ficha, soloLectura, estado) {
  const titulo = el("h1", { id: "titulo-revision", tabindex: "-1", texto: ficha.titular || `Ficha ${doc}` });
  const cabecera = document.querySelector(".encabezado-pagina");
  const texto = cabecera?.querySelector(".encabezado-texto");
  if (!texto) return titulo;
  cabecera.classList.add("encabezado-ficha");
  texto.replaceChildren(migas(doc), titulo,
    el("div", { clase: "encabezado-ficha-datos" }, estado(), soloLectura ? insigniaSoloLectura() : null,
      soloLectura ? el("p", { clase: "nota-solo-lectura", texto: NOTA_SOLO_LECTURA }) : null));
  cabecera.querySelector(".encabezado-acciones")?.replaceChildren(
    el("a", { clase: "boton secundario", href: "catalogar.html" }, icono("subir"), "Catalogar otra foto"));
  marcarArchivoActivo();
  document.title = `${ficha.titular || `Ficha ${doc}`} · Archivo · Fototeca Viva`;
  return titulo;
}

// ── (c) Ficha = Inspector ──
// La columna de la foto acompaña al inspector al desplazarse (pegajosa) solo si cabe entera en la ventana: si fuera más
// alta, sus avisos de abajo quedarían ocultos hasta el final del inspector.
let columnaFoto = null;
const MARGEN_PEGAJOSA = 32;
function ajustarColumnaFoto() {
  if (columnaFoto?.isConnected) columnaFoto.classList.toggle("pegajosa", columnaFoto.offsetHeight + MARGEN_PEGAJOSA <= window.innerHeight);
}
const observadorColumna = new ResizeObserver(ajustarColumnaFoto);
window.addEventListener("resize", ajustarColumnaFoto);

/**
 * Muestra una ficha. `comoPagina` (ficha guardada abierta con ?doc=): el encabezado de la página es el de la ficha.
 * Si no, la ficha lleva su barra («Ficha IPTC», resumen de la generación y «Catalogar otra foto») y el pie de la foto
 * dice el documento y su estado (una sola vez en la vista).
 */
function mostrarFicha(respuesta, { comoPagina = false } = {}) {
  const { documento_id: doc, ficha, fuentes = {}, meta = {} } = respuesta;
  let original = structuredClone(ficha);
  // Sin traza (fichas del archivo inicial): solo lectura, sin «Tu opinión» ni validación
  const soloLectura = !meta.traza_id;
  const estados = [];   // insignias de estado: se actualizan juntas al validar
  const estado = () => { const n = el("span", { clase: "estado-ficha" }, insignia(ficha.estado)); estados.push(n); return n; };

  let titulo;
  let barra = null;
  if (comoPagina) {
    titulo = encabezadoDeFicha(doc, ficha, soloLectura, estado);
  } else {
    titulo = el("h2", { id: "titulo-revision", tabindex: "-1" }, icono("catalogar"), "Ficha IPTC");
    const { control, region } = resumenGeneracion(meta);
    botonOtraFoto = el("button", { type: "button", clase: "boton secundario", id: "otra-foto", onclick: desplegarCarga },
      icono("subir"), "Catalogar otra foto");
    barra = el("header", { clase: "barra-ficha" },
      el("div", { clase: "barra-ficha-texto" }, titulo, control, soloLectura ? insigniaSoloLectura() : null),
      botonOtraFoto, region, soloLectura ? el("p", { clase: "barra-ficha-nota", texto: NOTA_SOLO_LECTURA }) : null);
  }

  // Inspector: Identificación, Accesibilidad, Descripciones y Palabras clave
  const palabras = campoPalabras(ficha.palabras_clave || [], fuentes.palabras_clave, soloLectura);
  const destino = el("div", { id: "resultado-opinion", "aria-live": "polite" });
  const estadoUtil = { valor: null };
  let pie = null;
  if (!soloLectura) {
    const grupoUtil = el("div", { clase: "fila", role: "group", "aria-labelledby": "pregunta-util" });
    const botonUtil = (valor, texto, nombreIcono) => el("button", { type: "button", clase: "boton secundario", "aria-pressed": "false",
      onclick: (ev) => {
        const pulsado = ev.currentTarget.getAttribute("aria-pressed") === "true";
        estadoUtil.valor = pulsado ? null : valor;
        grupoUtil.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
        if (!pulsado) ev.currentTarget.setAttribute("aria-pressed", "true");
      } }, icono(nombreIcono), texto);
    grupoUtil.append(botonUtil(true, "Útil", "check"), botonUtil(false, "No útil", "error"));
    pie = el("footer", { clase: "inspector-pie", role: "group", "aria-labelledby": "titulo-opinion" },
      el("h4", { id: "titulo-opinion", clase: "seccion-titulo", texto: "Tu opinión" }),
      el("div", { clase: "opinion-util" }, el("p", { id: "pregunta-util", texto: "¿Te fue útil la ficha?" }), grupoUtil),
      el("div", { clase: "opinion-comentario" }, el("label", { for: "comentario", texto: "Comentario (opcional)" }),
        el("textarea", { id: "comentario", rows: "2", maxlength: "1000" })),
      el("div", { clase: "fila acciones-ficha" },
        el("button", { type: "submit", clase: "boton", value: "validar" }, icono("check"), "Validar ficha"),
        el("button", { type: "submit", clase: "boton secundario", value: "opinar", texto: "Solo enviar opinión" })),
      destino);
  }
  const campos = Object.fromEntries(CAMPOS_TEXTO.map((c) => [c, campoTexto(c, ficha[c], fuentes[c], soloLectura)]));
  const formulario = el("form", { clase: "ficha", id: "formulario-ficha", "aria-labelledby": "titulo-inspector" },
    el("div", { clase: "panel-cuerpo" },
      seccion("seccion-identificacion", "Identificación", campos.titular),
      seccion("seccion-accesibilidad", "Accesibilidad", campos.texto_alternativo),
      seccion("seccion-descripciones", "Descripciones", campos.descripcion, campos.descripcion_extendida),
      seccion("palabras-titulo", "Palabras clave", palabras.nodo)),
    pie);
  formulario.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (soloLectura) return;
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
    ev.submitter?.setAttribute("aria-busy", "true");
    try {
      const { cuerpo } = await api("/retroalimentacion", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ traza_id: meta.traza_id, util: estadoUtil.valor, comentario: $("comentario").value.trim() || null,
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
        estados.forEach((n) => n.replaceChildren(insignia("validada")));
        texto = "Ficha validada: ahora es un ejemplo más para catalogar fotos parecidas.";
      }
      mensaje(destino, `${texto} (traza ${cuerpo.traza_id})`, "ok");
      anunciar(texto);
    } catch (e) {
      mensaje(destino, e.message);
    } finally {
      ev.submitter?.removeAttribute("aria-busy");
      botones.forEach((b) => { b.disabled = false; });
    }
  });

  // Foto: el mismo marco que en la espera (contain sobre la lupa); el visor muestra la copia guardada y la ficha tal
  // como está guardada (se actualiza al validar)
  const verGuardada = () => verFotoGuardada(doc, { titulo: "Foto guardada en el archivo", ficha: original, enlaceFicha: false,
    extra: [["Ruta", meta.ruta], ["Metadatos quitados al guardar", metadatosQuitados(meta)]] });
  const foto = el("figure", { clase: "foto" },
    el("button", { type: "button", clase: "boton-imagen marco-foto", "aria-label": "Ver en grande la foto guardada y su ficha", onclick: verGuardada },
      el("img", { src: `/api/fotos/${enc(doc)}/miniatura?lado=512`, width: "512", height: "384", decoding: "async",
        alt: ficha.texto_alternativo || `Foto ${doc} (sin texto alternativo todavía)` }),
      el("span", { clase: "lupa", "aria-hidden": "true" }, icono("lupa-foto"), "Ver en grande")),
    comoPagina ? null : el("figcaption", {}, el("span", { clase: "foto-documento" }, "Documento ", el("span", { clase: "id", texto: doc })),
      el("span", { clase: "foto-estado" }, el("span", { clase: "solo-lectores", texto: " · " }), "Estado: ", estado())));
  const listaAvisos = avisos(ficha, meta);
  const inspector = el("section", { clase: `panel inspector col-7${soloLectura ? " solo-lectura" : ""}`, "aria-labelledby": "titulo-inspector" },
    el("header", { clase: "panel-cabecera" }, icono("pluma"), el("h3", { id: "titulo-inspector", texto: "Campos de la ficha" }),
      soloLectura ? null : el("p", { clase: "panel-auxiliar", texto: "Edítalos y valida la ficha" })),
    formulario);

  const lateral = el("div", { clase: "ficha-lateral col-5" }, foto, panelProcedencia(ficha, fuentes),
    listaAvisos.length ? el("div", { clase: "avisos" }, ...listaAvisos) : null);
  revision.replaceChildren(...[barra, el("div", { clase: "reticula ficha-reticula" }, lateral, inspector), pieTecnico(meta)].filter(Boolean));
  revision.classList.toggle("como-pagina", comoPagina);
  observadorColumna.disconnect();
  columnaFoto = lateral;
  observadorColumna.observe(lateral);
  revision.hidden = false;
  plegarCarga();
  // Foco en el título (sin anillo) y la ficha arriba de la ventana
  titulo.focus({ preventScroll: true });
  desplazar(comoPagina ? document.querySelector(".encabezado-pagina") || revision : revision);
  anunciar(`Ficha lista: ${ficha.titular || "sin titular"}`);
}

// ── (b) Espera de una ficha (30–90 s en CPU) ──
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
 * Espera con la misma anatomía que tendrá la ficha: una barra de título arriba y, debajo, la foto en el mismo marco y
 * lugar (contain sobre la lupa, con una línea de escaneo sutil) y un panel con el tiempo transcurrido, la barra contra
 * el p95 de las fichas registradas (marca y etiqueta del p50) y los tiempos típicos por capa. No inventa la etapa actual
 * (el servicio no la reporta). Al terminar, la ficha ocupa su lugar y sus tiempos reales quedan en su barra. No es una
 * región viva: los lectores de pantalla oyen un aviso cada 20 s (anunciar), no uno por segundo.
 */
function panelEspera({ nombre = null, src = null, alt = "", detalle = "" } = {}) {
  const inicio = Date.now();
  const transcurrido = () => (Date.now() - inicio) / 1000;
  const titulo = el("h2", { id: "titulo-espera", tabindex: "-1" }, icono("reloj"), "Generando la ficha",
    nombre ? [" de «", el("span", { clase: "nombre-en-titulo", texto: nombre, title: nombre }), "»"] : null);
  const valorReloj = el("span", { clase: "reloj-valor", texto: "0:00" });
  const filaReloj = el("p", { clase: "reloj", "aria-hidden": "true" }, valorReloj, el("span", { clase: "reloj-etiqueta", texto: "transcurridos" }));
  const relleno = el("span", { clase: "progreso-relleno" });
  const marca = el("span", { clase: "progreso-marca" });
  const barra = el("div", { clase: "progreso espera-progreso", "aria-hidden": "true", hidden: true }, relleno, marca);
  const etiquetaP50 = el("span", { clase: "etiqueta-p50" });
  const escala = el("div", { clase: "progreso-escala", "aria-hidden": "true", hidden: true }, etiquetaP50);
  const referencia = el("p", { clase: "espera-referencia", texto: "Consultando cuánto suelen tardar las fichas…" });
  const subtitulo = el("h3", { texto: "Tiempos típicos por capa (p50)" });
  const { lista, valores } = listaCapas();
  let nota = el("p", { clase: "nota-espera" }, icono("info"),
    el("span", { texto: "La petición sigue en curso aunque no veas cambios: no recargues ni cierres la página." }));
  const foto = src ? el("figure", { clase: "foto col-5" }, el("div", { clase: "marco-foto escaneo" }, el("img", { src, alt, decoding: "async" })),
    nombre || detalle ? el("figcaption", {}, el("span", { clase: "nombre-archivo", texto: nombre || "" }),
      detalle ? el("span", { clase: "fotograma", texto: detalle }) : null) : null) : null;
  const datos = el("div", { clase: `panel espera-datos ${foto ? "col-7" : "col-12"}` },
    el("div", { clase: "panel-cuerpo" }, filaReloj, barra, escala, referencia, subtitulo, lista, nota));
  const nodo = el("section", { clase: "espera", "aria-labelledby": "titulo-espera" },
    el("header", { clase: "barra-ficha barra-espera" }, el("div", { clase: "barra-ficha-texto" }, titulo)),
    el("div", { clase: "reticula ficha-reticula" }, foto, datos));
  let p50 = null;
  let p95 = null;
  let vigente = true;
  let siguienteAnuncio = ANUNCIO_CADA_S;
  const tic = () => {
    const s = transcurrido();
    valorReloj.textContent = reloj(s);
    if (p95) {
      relleno.style.width = `${Math.min(100, (s / p95) * 100).toFixed(1)}%`;
      if (s > p95 && !nodo.classList.contains("lenta")) {
        nodo.classList.add("lenta");
        barra.classList.add("lenta");
        const aviso = crearMensaje("Está tardando más que el 95 % de las fichas, pero la petición sigue en curso: no recargues ni "
          + "cierres la página.", "aviso");
        nota.replaceWith(aviso);
        nota = aviso;
      }
    }
    if (s >= siguienteAnuncio) {
      siguienteAnuncio += ANUNCIO_CADA_S;
      anunciar(`Generando la ficha: ${reloj(s)} transcurridos${p50 ? `; suele tardar ${reloj(p50)}` : ""}.`);
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
    const posicion = Math.min(100, (p50 / p95) * 100);
    marca.style.left = `${posicion.toFixed(1)}%`;
    etiquetaP50.style.left = `${Math.min(88, Math.max(12, posicion)).toFixed(1)}%`;
    etiquetaP50.replaceChildren("p50 ", el("span", { clase: "valor", texto: reloj(p50) }));
    barra.hidden = false;
    escala.hidden = false;
    referencia.textContent = `Según las ${numero(f.total.n)} fichas registradas: la mitad termina antes de ${reloj(p50)} (la marca) `
      + `y la barra se llena en el p95, ${reloj(p95)}.`;
    for (const k of ORDEN_CAPAS) if (f[k]?.n) valores[k].textContent = segundos(f[k].p50_ms);
    tic();
  });
  const detener = () => {
    vigente = false;
    clearInterval(reloj1s);
    nodo.remove();
  };
  return {
    nodo,
    enfocar: () => {
      titulo.focus({ preventScroll: true });
      desplazar(nodo);
    },
    terminar: detener,   // la ficha ocupa su lugar; sus tiempos reales quedan en la barra de la ficha
    fallar: detener,
  };
}

function mostrarError(contenedor, e) {
  mensaje(contenedor, `${e.message}${e.traza ? ` (traza ${e.traza})` : ""}`);
  const aviso = contenedor.firstElementChild;
  if (aviso) { aviso.tabIndex = -1; aviso.focus(); }
}

/** POST /api/fichas con el panel de espera, el formulario plegado, el botón ocupado y el aviso al salir de la página. */
async function generarFicha(opciones, vista = {}) {
  if (ocupado) return;
  const panel = panelEspera(vista);
  espera.replaceChildren(panel.nodo);
  progreso.replaceChildren();
  revision.hidden = true;
  marcarOcupado(true);
  plegarCarga();
  panel.enfocar();
  window.addEventListener("beforeunload", avisarAlSalir);
  try {
    const { cuerpo } = await api("/fichas", { method: "POST", ...opciones });
    panel.terminar();
    mostrarFicha(cuerpo);
  } catch (e) {
    panel.fallar();
    formularioCarga.hidden = false;   // la foto sigue elegida: se puede reintentar
    mostrarError(progreso, e);
  } finally {
    window.removeEventListener("beforeunload", avisarAlSalir);
    marcarOcupado(false);
  }
}

// ── (d) Lote ──
function tarjetaLote(f, i) {
  return el("li", {}, el("button", { type: "button", clase: "tarjeta-lote", onclick: () => mostrarFicha(f) },
    miniatura(f.documento_id, { alt: "", diferida: i >= 8 }),
    el("span", { clase: "tarjeta-lote-titular", texto: f.ficha.titular || "Sin titular" }),
    el("span", { clase: "tarjeta-lote-pie" }, insignia(f.ficha.estado),
      el("span", { clase: "tarjeta-lote-accion" }, "Revisar", icono("chevron")))));
}

const tarjetaPendiente = () => el("li", { "aria-hidden": "true" }, el("div", { clase: "tarjeta-lote pendiente" },
  el("span", { clase: "esqueleto foto" }), el("span", { clase: "esqueleto linea" }),
  el("span", { clase: "tarjeta-lote-pie" }, insignia("pendiente"))));

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
    const nota = rechazados.length ? el("div", { clase: "mensaje error con-icono", role: "alert" }, icono("error", "mensaje-icono"),
      el("div", { clase: "mensaje-texto", texto: `${plural(rechazados.length, "archivo rechazado", "archivos rechazados")}: `
        + rechazados.map((d) => `${d.nombre} (${d.error.mensaje})`).join("; ") })) : null;
    const { cuerpo: lote } = await api("/lotes", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ documento_ids: ids }) });
    const barra = el("progress", { max: String(lote.total), value: "0", id: "barra-lote", "aria-labelledby": "texto-lote" });
    const texto = el("p", { id: "texto-lote", clase: "lote-texto", role: "status", texto: `0 de ${lote.total} fichas listas` });
    const errores = el("div");
    // El progreso vive dentro del panel del lote: catalogar otra foto mientras tanto no lo borra
    progreso.replaceChildren();
    loteProgreso.replaceChildren(...[barra, texto, nota, errores].filter(Boolean));
    loteResumen.replaceChildren(insignia("en_curso"));
    listaLote.replaceChildren(...Array.from({ length: lote.total }, tarjetaPendiente));
    seccionLote.hidden = false;
    // Las fotos ya están en el lote: el formulario queda libre para elegir otras
    formularioCarga.reset();
    mostrarElegidas([]);
    let pintadas = 0;
    const consultar = async () => {
      try {
        const { cuerpo: estado } = await api(`/lotes/${enc(lote.lote_id)}`);
        barra.value = estado.completadas + estado.fallidas;
        texto.textContent = `${estado.completadas} de ${estado.total} fichas listas${estado.fallidas ? ` · ${estado.fallidas} fallidas` : ""}`;
        errores.replaceChildren(...(estado.errores || []).map((e) => crearMensaje(`${e.documento_id}: ${e.mensaje}`, "error")));
        // Solo se agregan las tarjetas nuevas: las ya pintadas no se vuelven a pedir ni pierden el foco
        listaLote.querySelectorAll("li[aria-hidden]").forEach((n) => n.remove());
        listaLote.append(...(estado.fichas || []).slice(pintadas).map((f, i) => tarjetaLote(f, pintadas + i)));
        pintadas = (estado.fichas || []).length;
        const pendientes = Math.max(0, estado.total - estado.completadas - estado.fallidas);
        listaLote.append(...Array.from({ length: estado.estado === "terminado" ? 0 : pendientes }, tarjetaPendiente));
        if (estado.estado !== "terminado") setTimeout(consultar, 3000);
        else {
          loteResumen.replaceChildren(insignia(estado.fallidas && !estado.completadas ? "error" : "listo"));
          anunciar(`El lote terminó: ${estado.completadas} fichas listas${estado.fallidas ? `, ${estado.fallidas} fallidas` : ""}.`);
        }
      } catch (e) { mensaje(errores, e.message); }
    };
    consultar();
  } catch (e) {
    mostrarError(progreso, e);
  } finally {
    marcarOcupado(false);
  }
}

// ── (a) Carga: fotos elegidas ──
function estadoDeCarga(texto, error = false) {
  estadoCarga.classList.toggle("error", error);
  estadoCarga.replaceChildren(...(error ? [icono("error"), el("span", { texto })] : [texto]));
}

/** Jerarquía de la carga: sin fotos, «Elegir fotos» es la acción primaria y «Catalogar» se ve deshabilitado (sigue
 *  enfocable y explica qué falta); con fotos, «Catalogar» pasa a primaria. */
function marcarHayFotos(hay) {
  etiquetaElegir.classList.toggle("secundario", hay);
  textoElegir.textContent = hay ? "Elegir otras fotos" : "Elegir fotos";
  if (hay) botonCatalogar.removeAttribute("aria-disabled");
  else botonCatalogar.setAttribute("aria-disabled", "true");
}

/** Vista previa de las fotos elegidas, antes de subirlas: se ven tal como están en tu equipo. */
function mostrarElegidas(archivos) {
  urlsPrevias.forEach((u) => URL.revokeObjectURL(u));
  const imagenes = archivos.filter((a) => /^image\/(jpeg|png)$/.test(a.type));
  const visibles = imagenes.slice(0, MAX_PREVIAS);
  urlsPrevias = visibles.map((a) => URL.createObjectURL(a));
  elegidas.hidden = !visibles.length;
  tituloElegidas.textContent = imagenes.length === 1 ? "1 foto elegida" : `${numero(imagenes.length)} fotos elegidas`;
  const items = visibles.map((a, i) => {
    const url = urlsPrevias[i];
    const medidas = el("span", { clase: "medidas" });
    const img = el("img", { src: url, alt: `Vista previa de ${a.name}`, decoding: "async" });
    const datos = () => [["Archivo", a.name], ["Tamaño", tamano(a.size)], ["Tipo", a.type],
      ["Medidas originales", img.naturalWidth ? `${img.naturalWidth} × ${img.naturalHeight} px` : null],
      ["Al guardarla", "El servicio quita el GPS, el número de serie de la cámara y los datos del autor antes de guardarla."]];
    img.addEventListener("load", () => { medidas.textContent = `${img.naturalWidth} × ${img.naturalHeight}`; medidas.title = "Medidas en píxeles"; });
    return el("li", {}, el("figure", { clase: "montura" },
      el("button", { type: "button", clase: "boton-imagen", "aria-label": `Ver en grande ${a.name}`,
        onclick: () => abrirVisor({ src: url, alt: `Foto elegida: ${a.name}`, titulo: `Foto elegida: ${a.name}`, datos: datos(),
          nota: "Es el archivo original, todavía en tu equipo: aún no se ha subido." }) },
        img, el("span", { clase: "lupa", "aria-hidden": "true" }, icono("lupa-foto"), "Ver")),
      el("figcaption", {}, el("span", { clase: "nombre-archivo", texto: a.name, title: a.name }),
        el("span", { clase: "fotograma" }, el("span", { texto: tamano(a.size) }), medidas))));
  });
  if (imagenes.length > visibles.length) items.push(el("li", { clase: "mas-fotos", texto: `y ${imagenes.length - visibles.length} fotos más` }));
  vistaPrevia.replaceChildren(...items);
  const otros = archivos.length - imagenes.length;
  const nota = otros ? ` ${plural(otros, "archivo no es", "archivos no son")} JPEG ni PNG: el servicio ${otros === 1 ? "lo" : "los"} rechazará.` : "";
  textoBoton.textContent = archivos.length > 1 ? `Catalogar ${numero(archivos.length)} fotos` : archivos.length ? "Catalogar la foto" : "Catalogar";
  marcarHayFotos(archivos.length > 0);
  estadoDeCarga(!archivos.length ? "Elige una o varias fotos para empezar."
    : archivos.length === 1 ? `Lista para catalogar: verás su ficha al terminar.${nota}`
      : `Se catalogarán en lote, con barra de progreso.${nota}`, Boolean(otros) && !imagenes.length);
  if (imagenes.length === 1) tiemposTipicos();   // se adelanta la consulta del tiempo típico para la espera
  if (imagenes.length) anunciar(imagenes.length === 1 ? "1 foto elegida: puedes verla antes de catalogar" : `${imagenes.length} fotos elegidas`);
}

entradaFotos.addEventListener("change", (ev) => mostrarElegidas([...ev.target.files]));

formularioCarga.addEventListener("submit", (ev) => {
  ev.preventDefault();
  if (ocupado) return;   // un solo POST a la vez, aunque se pulse Enter o el botón dos veces
  const archivos = [...entradaFotos.files];
  if (!archivos.length) {
    estadoDeCarga("Elige al menos una foto JPEG o PNG para catalogar.", true);
    anunciar("Elige al menos una foto JPEG o PNG para catalogar.");
    entradaFotos.focus();
    return;
  }
  if (archivos.length === 1) {
    const a = archivos[0];
    const datos = new FormData();
    datos.append("foto", a);
    generarFicha({ body: datos }, { nombre: a.name, src: urlsPrevias[0] || null, alt: `Foto que se está catalogando: ${a.name}`,
      detalle: tamano(a.size) });
  } else {
    seccionLote.hidden = true;
    catalogarLote(archivos);
  }
});

// Arrastrar y soltar sobre la mesa de luz (el contador evita el parpadeo al pasar sobre los elementos de dentro)
let arrastres = 0;
zona.addEventListener("dragenter", (e) => { e.preventDefault(); arrastres += 1; zona.classList.add("activa"); });
zona.addEventListener("dragover", (e) => { e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = "copy"; });
zona.addEventListener("dragleave", () => { arrastres = Math.max(0, arrastres - 1); if (!arrastres) zona.classList.remove("activa"); });
zona.addEventListener("drop", (e) => {
  e.preventDefault();
  arrastres = 0;
  zona.classList.remove("activa");
  if (!e.dataTransfer?.files.length) return;
  entradaFotos.files = e.dataTransfer.files;
  mostrarElegidas([...e.dataTransfer.files]);
});
// Una foto soltada fuera de la mesa no hace que el navegador abra el archivo (y se pierda la página)
window.addEventListener("dragover", (e) => { if (!zona.contains(e.target)) e.preventDefault(); });
window.addEventListener("drop", (e) => { if (!zona.contains(e.target)) e.preventDefault(); });

// catalogar.html?doc=ID → la ficha guardada como página (o se genera si la foto todavía no tiene)
const doc = new URLSearchParams(location.search).get("doc");
if (doc) {
  plegarCarga();
  encabezadoProvisional(doc);
  mensaje(progreso, `Cargando la ficha de ${doc}…`, "info");
  (async () => {
    try {
      const { cuerpo } = await api(`/fichas/${enc(doc)}`, { aceptar: [404] });
      progreso.replaceChildren();
      if (cuerpo?.ficha) {
        mostrarFicha({ documento_id: doc, ficha: cuerpo.ficha, fuentes: cuerpo.fuentes,
          meta: { traza_id: cuerpo.traza_id, ruta: `guardada (${cuerpo.origen})`, cache: "ninguna", modelos: {}, tiempos_por_capa_ms: {} } },
        { comoPagina: true });
      } else {
        await generarFicha({ headers: { "Content-Type": "application/json" }, body: JSON.stringify({ documento_id: doc }) },
          { src: `/api/fotos/${enc(doc)}/miniatura?lado=512`, alt: `Foto ${doc}`, detalle: doc });
      }
    } catch (e) {
      formularioCarga.hidden = false;
      mostrarError(progreso, e);
    }
  })();
} else {
  marcarHayFotos(false);
}
