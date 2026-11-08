// Catalogar: subir fotos → ficha (o lote) → revisar con fuentes → retroalimentación y validación.
import { api, anunciar, el, ETIQUETA_ESTADO, insignia } from "./api.js";
import { mensaje, pieTecnico, textoGuardrail } from "./comun.js";

const ETIQUETAS_CAMPO = {
  titular: "Titular", texto_alternativo: "Texto alternativo", descripcion: "Descripción",
  descripcion_extendida: "Descripción extendida", palabras_clave: "Palabras clave",
};
const CAMPOS_TEXTO = ["titular", "texto_alternativo", "descripcion", "descripcion_extendida"];
const MAXIMOS = { titular: 120, texto_alternativo: 250, descripcion: 800, descripcion_extendida: 1200 };
const progreso = document.getElementById("progreso");
const revision = document.getElementById("revision");
const OTRA_PESTANA = { target: "_blank", rel: "noopener" };

/** Fuente de un campo como chip: foto similar (con miniatura), regla, término del tesauro (con su URI) o archivista. */
function chipFuente(f) {
  const puntaje = f.puntaje != null ? ` · ${f.puntaje}` : "";
  if (f.tipo === "foto_similar") {
    return el("a", { clase: "chip chip-foto", href: `catalogar.html?doc=${encodeURIComponent(f.id)}`, ...OTRA_PESTANA,
      title: f.titulo ? `Foto similar: ${f.titulo}` : `Foto similar ${f.id}` },
      el("img", { src: `/api/fotos/${encodeURIComponent(f.id)}/miniatura?lado=96`, alt: "", width: "24", height: "24" }),
      `Foto similar${puntaje}`,
      el("span", { clase: "solo-lectores", texto: `: ${f.titulo || f.id} (se abre en otra pestaña)` }));
  }
  if (f.tipo === "tesauro") {
    const texto = `Tesauro: ${f.titulo || f.id}${puntaje}`;
    return /^https?:/.test(f.id || "")
      ? el("a", { clase: "chip chip-tesauro", href: f.id, ...OTRA_PESTANA, title: f.id }, texto,
        el("span", { clase: "solo-lectores", texto: ` (URI ${f.id}, se abre en otra pestaña)` }))
      : el("span", { clase: "chip chip-tesauro", title: f.id }, texto);
  }
  if (f.tipo === "regla") {
    const texto = `Regla: ${f.titulo || f.id}${puntaje}`;
    const extra = el("span", { clase: "solo-lectores", texto: ` (fragmento ${f.id})` });
    return f.url
      ? el("a", { clase: "chip chip-regla", href: f.url, ...OTRA_PESTANA, title: f.id }, texto, extra)
      : el("span", { clase: "chip chip-regla", title: `Fragmento ${f.id}` }, texto, extra);
  }
  const texto = f.tipo === "archivista" ? "Corrección del archivista" : f.tipo === "referencia_humana" ? "Descripción humana de referencia"
    : f.tipo === "etiqueta_open_images" ? `Etiqueta: ${f.titulo || f.id}` : `${f.tipo}: ${f.id}`;
  return el("span", { clase: `chip chip-${f.tipo}`, title: f.id }, texto + puntaje);
}

function campoEditable(nombre, valor, fuentes) {
  const id = `campo-${nombre}`;
  const control = nombre === "titular"
    ? el("input", { id, name: nombre, type: "text", value: valor || "", maxlength: MAXIMOS[nombre] })
    : el("textarea", { id, name: nombre, rows: nombre === "texto_alternativo" ? "3" : "4", maxlength: MAXIMOS[nombre] }, valor || "");
  const contador = el("span", { clase: "contador", id: `${id}-contador` });
  const actualizar = () => { contador.textContent = `${control.value.length}/${MAXIMOS[nombre]} caracteres`; };
  control.addEventListener("input", actualizar);
  // Enter en el titular no debe enviar el formulario (el primer botón es «Validar ficha»)
  if (nombre === "titular") control.addEventListener("keydown", (ev) => { if (ev.key === "Enter") ev.preventDefault(); });
  control.setAttribute("aria-describedby", `${id}-contador ${id}-fuentes`);
  actualizar();
  return el("div", { clase: "campo" },
    el("label", { for: id, texto: ETIQUETAS_CAMPO[nombre] }), control, contador,
    el("div", { clase: "fuentes", id: `${id}-fuentes` },
      el("span", { clase: "solo-lectores", texto: "Fuentes: " }),
      (fuentes || []).length ? fuentes.map(chipFuente) : el("span", { clase: "sin-fuente", texto: "Sin fuente verificable" })));
}

function campoPalabras(palabras, fuentes) {
  const lista = el("ul", { clase: "palabras", id: "palabras-lista", "aria-label": "Palabras clave de la ficha" });
  const items = [...palabras];
  const pintar = () => lista.replaceChildren(...items.map((p, i) => el("li", { clase: `chip chip-${p.origen}` },
    p.origen === "tesauro" && p.uri
      ? el("a", { href: p.uri, ...OTRA_PESTANA, title: p.uri }, p.termino, el("span", { clase: "solo-lectores", texto: " (término del tesauro, se abre en otra pestaña)" }))
      : p.termino,
    el("button", { type: "button", clase: "quitar", "aria-label": `Quitar ${p.termino}`, onclick: () => {
      items.splice(i, 1); pintar(); anunciar(`Se quitó ${p.termino}`); entrada.focus();
    } }, "×"))));
  const entrada = el("input", { id: "palabra-nueva", type: "text", maxlength: "80" });
  const agregar = () => {
    const t = entrada.value.trim();
    if (t) { items.push({ termino: t, origen: "libre" }); pintar(); entrada.value = ""; entrada.focus(); anunciar(`Se agregó ${t}`); }
  };
  entrada.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); agregar(); } });
  pintar();
  return {
    nodo: el("div", { clase: "campo" }, el("p", { clase: "etiqueta", id: "palabras-titulo", texto: "Palabras clave" }), lista,
      el("label", { for: "palabra-nueva", clase: "solo-lectores", texto: "Agregar palabra clave" }),
      el("div", { clase: "fila" }, entrada, el("button", { type: "button", clase: "boton secundario", onclick: agregar }, "Agregar palabra")),
      el("div", { clase: "fuentes", id: "campo-palabras_clave-fuentes" }, el("span", { clase: "solo-lectores", texto: "Fuentes: " }),
        (fuentes || []).slice(0, 10).map(chipFuente))),
    items,
    reemplazar: (nuevas) => { items.splice(0, items.length, ...nuevas); pintar(); },
  };
}

function avisos(ficha, meta) {
  const nodos = [];
  if (meta?.duplicado_de) {
    nodos.push(el("div", { clase: "mensaje aviso", role: "status" },
      "Posible duplicado de ", el("a", { href: `catalogar.html?doc=${encodeURIComponent(meta.duplicado_de.documento_id)}`, texto: meta.duplicado_de.documento_id }),
      ` (similitud ${meta.duplicado_de.similitud}). Se reutilizó su ficha: revísala antes de validarla.`));
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

function mostrarFicha(respuesta) {
  const { documento_id: doc, ficha, fuentes = {}, meta = {} } = respuesta;
  let original = structuredClone(ficha);
  revision.hidden = false;
  const estadoFicha = el("span", {}, insignia(ficha.estado));
  const palabras = campoPalabras(ficha.palabras_clave || [], fuentes.palabras_clave);
  const estadoUtil = { valor: null };
  const grupoUtil = el("div", { clase: "fila", role: "group", "aria-labelledby": "pregunta-util" });
  const botonUtil = (valor, texto) => el("button", { type: "button", clase: "boton secundario", "aria-pressed": "false",
    onclick: (ev) => {
      const pulsado = ev.currentTarget.getAttribute("aria-pressed") === "true";
      estadoUtil.valor = pulsado ? null : valor;
      grupoUtil.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
      if (!pulsado) ev.currentTarget.setAttribute("aria-pressed", "true");
    } }, texto);
  grupoUtil.append(botonUtil(true, "Útil"), botonUtil(false, "No útil"));
  const destino = el("div", { id: "resultado-opinion", "aria-live": "polite" });
  const sinTraza = !meta.traza_id;
  const formulario = el("form", { clase: "ficha", id: "formulario-ficha" },
    CAMPOS_TEXTO.map((c) => campoEditable(c, ficha[c], fuentes[c])),
    palabras.nodo,
    el("fieldset", { clase: "opinion", disabled: sinTraza }, el("legend", { texto: "Tu opinión" }),
      el("p", { id: "pregunta-util", clase: "etiqueta", texto: "¿Te fue útil la ficha?" }), grupoUtil,
      el("label", { for: "comentario", texto: "Comentario (opcional)" }),
      el("textarea", { id: "comentario", rows: "2", maxlength: "1000" })),
    sinTraza ? el("p", { clase: "mensaje aviso", texto: "Esta ficha no tiene traza (viene del archivo inicial); no se puede calificar ni validar desde aquí." }) : null,
    el("div", { clase: "fila" },
      el("button", { type: "submit", clase: "boton", value: "validar", disabled: sinTraza, texto: "Validar ficha" }),
      el("button", { type: "submit", clase: "boton secundario", value: "opinar", disabled: sinTraza, texto: "Solo enviar opinión" })),
    destino);
  formulario.addEventListener("submit", async (ev) => {
    ev.preventDefault();
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
  revision.replaceChildren(
    el("h2", { id: "titulo-revision", tabindex: "-1", texto: "Revisa la ficha" }),
    el("div", { clase: "revision" },
      el("figure", { clase: "foto" },
        el("img", { src: `/api/fotos/${encodeURIComponent(doc)}/miniatura`, alt: ficha.texto_alternativo || `Foto ${doc} (sin texto alternativo todavía)` }),
        el("figcaption", {}, `Documento ${doc} · Estado: `, estadoFicha)),
      el("div", {}, ...avisos(ficha, meta), formulario)),
    pieTecnico(meta));
  document.getElementById("titulo-revision").focus();
  anunciar(`Ficha lista: ${ficha.titular || "sin titular"}`);
}

function cronometro(texto) {
  const inicio = Date.now();
  const nodo = el("p", { clase: "mensaje ok", role: "status" });
  const tic = () => { nodo.textContent = `${texto} (${Math.round((Date.now() - inicio) / 1000)} s)`; };
  tic();
  const id = setInterval(tic, 1000);
  return { nodo, parar: () => clearInterval(id) };
}

async function catalogarUna(archivo) {
  const reloj = cronometro("Generando la ficha: describiendo la foto, buscando ejemplos y reglas…");
  progreso.replaceChildren(reloj.nodo);
  const datos = new FormData();
  datos.append("foto", archivo);
  try {
    const { cuerpo } = await api("/fichas", { method: "POST", body: datos });
    progreso.replaceChildren();
    mostrarFicha(cuerpo);
  } catch (e) { mensaje(progreso, e.message); } finally { reloj.parar(); }
}

async function catalogarLote(archivos) {
  const datos = new FormData();
  datos.append("tipo", "foto");
  for (const a of archivos) datos.append("archivos", a);
  mensaje(progreso, `Subiendo ${archivos.length} fotos…`, "ok");
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
    progreso.replaceChildren(barra, texto, nota, errores);
    document.getElementById("lote").hidden = false;
    const consultar = async () => {
      try {
        const { cuerpo: estado } = await api(`/lotes/${encodeURIComponent(lote.lote_id)}`);
        barra.value = estado.completadas + estado.fallidas;
        texto.textContent = `${estado.completadas} de ${estado.total} fichas listas${estado.fallidas ? ` · ${estado.fallidas} fallidas` : ""}`;
        errores.replaceChildren(...(estado.errores || []).map((e) => el("p", { clase: "mensaje error", texto: `${e.documento_id}: ${e.mensaje}` })));
        document.getElementById("lista-lote").replaceChildren(...estado.fichas.map((f) => el("button", { type: "button", clase: "tarjeta tarjeta-boton", onclick: () => mostrarFicha(f) },
          el("img", { src: `/api/fotos/${encodeURIComponent(f.documento_id)}/miniatura?lado=256`, alt: f.ficha.texto_alternativo || `Foto ${f.documento_id}` }),
          el("strong", { texto: f.ficha.titular || f.documento_id }),
          el("span", { texto: `Estado: ${ETIQUETA_ESTADO[f.ficha.estado] || f.ficha.estado} · revisar` }))));
        if (estado.estado !== "terminado") setTimeout(consultar, 3000);
        else anunciar(`El lote terminó: ${estado.completadas} fichas listas${estado.fallidas ? `, ${estado.fallidas} fallidas` : ""}.`);
      } catch (e) { mensaje(errores, e.message); }
    };
    consultar();
  } catch (e) { mensaje(progreso, e.message); }
}

document.getElementById("formulario-carga").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const archivos = [...document.getElementById("fotos").files];
  if (!archivos.length) return;
  revision.hidden = true;
  document.getElementById("lote").hidden = true;
  if (archivos.length === 1) catalogarUna(archivos[0]); else catalogarLote(archivos);
});

const zona = document.getElementById("zona-soltar");
zona.addEventListener("dragover", (e) => { e.preventDefault(); zona.classList.add("activa"); });
zona.addEventListener("dragleave", () => zona.classList.remove("activa"));
zona.addEventListener("drop", (e) => {
  e.preventDefault();
  zona.classList.remove("activa");
  document.getElementById("fotos").files = e.dataTransfer.files;
  anunciar(`${e.dataTransfer.files.length} fotos listas para catalogar`);
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
        const reloj = cronometro("Generando la ficha…");
        progreso.replaceChildren(reloj.nodo);
        try {
          const { cuerpo: r } = await api("/fichas", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ documento_id: doc }) });
          progreso.replaceChildren();
          mostrarFicha(r);
        } finally { reloj.parar(); }
      }
    } catch (e) { mensaje(progreso, e.message); }
  })();
}
