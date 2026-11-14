// Buscar · v4 «Mesa de luz»: por texto (POST /api/busquedas JSON) o por foto (multipart). La estructura es la de v3
// (el campo, los ejemplos, la búsqueda por foto, los resultados con sus razones y la consulta interpretada); cambia la
// piel: cada resultado es un fotograma de una hoja de contactos y su número de cuadro es el rango (una secuencia real).
// El fotograma abre el visor; el titular, la ficha. La línea de #estado dice cuántos, por qué ruta y en cuánto tiempo;
// el pie técnico, el resto. Inicio llega con ?q=… (busca al cargar) o con #con-foto (abre la búsqueda por foto).
import { api, anunciar, el } from "./api.js";
import * as comun from "./comun.js";

const { crearMensaje, mensaje, miniatura, numero, pieTecnico, segundos, verFotoGuardada } = comun;
const estado = document.getElementById("estado");
const resultados = document.getElementById("resultados");
const interpretada = document.getElementById("interpretada");
const tecnico = document.getElementById("tecnico");
const consulta = document.getElementById("consulta");
const formularioTexto = document.getElementById("formulario-texto");
const formularioFoto = document.getElementById("formulario-imagen");
const alternarFoto = document.getElementById("alternar-foto");
const entradaFoto = document.getElementById("imagen");
const botonBuscar = formularioTexto.querySelector("button[type=submit]");
const VISIBLES_SIN_DIFERIR = 8;   // las dos primeras filas cargan de inmediato; el resto, al acercarse
let turno = 0;                    // solo pinta la respuesta de la búsqueda más reciente

const RUTAS = { simple: "por la ruta simple", compleja: "por la ruta compleja", imagen: "con una foto" };
const esPenalizacion = (razon) => /^penaliz/i.test(razon);
/** Trazo de lápiz graso (comun.js · marcaLapiz); si la base aún no lo tiene, no se dibuja nada. */
const lapiz = (tipo) => (typeof comun.marcaLapiz === "function" ? comun.marcaLapiz(tipo) : null);

/** Un resultado = un fotograma: la foto (abre el visor), el número de cuadro (el rango) y, bajo la tira, el pie con el
 *  titular (lleva a la ficha) y las razones por las que coincide. */
function cuadro(x, i) {
  const titular = x.titular || "Foto sin ficha";
  const alt = x.texto_alternativo || x.titular || `Resultado ${i + 1} (foto sin ficha)`;
  const idTitular = `resultado-${i + 1}`;
  const razones = x.razones || [];
  // Solo el rango: el orden sale de fusionar dos listas (RRF) con penalizaciones, y `puntaje` de la API es solo la
  // similitud texto→imagen, que ya aparece en las razones (un puntaje junto al rango no cuadraba con el orden).
  // El marco: la foto y su número sobre la película (el círculo de lápiz graso, dentro de la foto, aparece al pasar o
  // enfocar); el pie va en la mesa, bajo la tira
  const marco = el("div", { clase: "cuadro-marco" },
    el("button", { type: "button", clase: "cuadro-foto", title: titular,
      onclick: () => verFotoGuardada(x.documento_id, { titulo: titular,
        extra: [["Posición", numero(i + 1)], ["Por qué coincide", razones.join("; ")]] }) },
      miniatura(x.documento_id, { alt, diferida: i >= VISIBLES_SIN_DIFERIR }),
      el("span", { clase: "solo-lectores", texto: " (ver en grande con su ficha)" }), lapiz("circulo")),
    el("span", { clase: "cuadro-num" }, el("span", { clase: "solo-lectores", texto: "Posición " }), numero(i + 1)));
  return el("li", { clase: "cuadro" }, el("article", { clase: "cuadro-articulo", "aria-labelledby": idTitular },
    marco,
    el("div", { clase: "cuadro-pie" },
      el("h3", { clase: "resultado-titular", id: idTitular },
        el("a", { href: `catalogar.html?doc=${encodeURIComponent(x.documento_id)}`, title: titular, texto: titular })),
      el("p", { clase: "solo-lectores", texto: "Por qué coincide:" }),
      el("ul", { clase: "razones" }, razones.map((razon) => el("li", { clase: esPenalizacion(razon) ? "penalizada" : null },
        esPenalizacion(razon) ? el("span", { clase: "razon-simbolo", "aria-hidden": "true", texto: "!" }) : null, razon))))));
}

/** Marcadores mientras llega la respuesta (no son article: no son resultados). */
const esqueletos = (n = 8) => el("ol", { clase: "tira hoja-resultados cargando", "aria-hidden": "true" },
  Array.from({ length: n }, () => el("li", { clase: "cuadro cargando" }, el("span", { clase: "esqueleto foto" }))));

/** Línea de resultados, en prosa: cuántos, por qué ruta, en cuánto tiempo y si vino de la caché. */
function resumen(meta, n) {
  const partes = [el("strong", { texto: n === 1 ? "1 resultado" : `${numero(n)} resultados` })];
  if (RUTAS[meta.ruta]) partes.push(` ${RUTAS[meta.ruta]}`);
  if (typeof meta.tiempo_ms === "number") partes.push(" en ", el("span", { clase: "mono", texto: segundos(meta.tiempo_ms) }));
  if (meta.cache && meta.cache !== "ninguna") partes.push(`, desde la caché (${meta.cache})`);
  partes.push(".");
  const linea = crearMensaje(partes, n ? "ok" : "info");
  linea.classList.add("resumen");
  return linea;
}

const par = (termino, valor) => el("div", {}, el("dt", { texto: termino }), el("dd", {}, valor));

function pintarInterpretada(q) {
  const personas = q.filtros?.contiene_personas;
  interpretada.replaceChildren(
    el("h2", { id: "titulo-interpretada", texto: "Consulta interpretada" }),
    el("p", { clase: "interpretada-nota", texto: "Así la descompuso el modelo de lenguaje." }),
    el("dl", { clase: "interpretada" },
      par("Qué debe verse", q.consulta_semantica || "—"),
      par("Qué excluir", (q.excluir || []).join(", ") || "Nada"),
      par("¿Con personas?", personas === true ? "Sí" : personas === false ? "No" : "Indistinto"),
      par("Términos del tesauro", (q.terminos_tesauro || []).join(", ") || "—")));
  interpretada.hidden = false;
}

/** Lleva «Resultados» a la parte de arriba si quedó fuera de la vista (suave, salvo con movimiento reducido). */
function mostrarResultados() {
  const barra = document.querySelector(".resultados-barra");
  const arriba = barra.getBoundingClientRect().top;
  if (arriba >= 0 && arriba <= innerHeight * 0.35) return;
  const reducido = matchMedia("(prefers-reduced-motion: reduce)").matches;
  barra.scrollIntoView({ behavior: reducido ? "auto" : "smooth", block: "start" });
}

function pintar(cuerpo) {
  const r = cuerpo.resultados || [];
  const meta = cuerpo.meta || {};
  resultados.replaceChildren(r.length
    ? el("ol", { clase: "tira hoja-resultados", "aria-labelledby": "titulo-resultados" }, r.map(cuadro))
    : el("p", { clase: "resultados-inicial", texto: cuerpo.mensaje
      || "Ninguna foto del archivo coincide lo suficiente. Prueba con otras palabras, con menos condiciones o con una foto parecida." }));
  if (meta.ruta === "compleja" && cuerpo.consulta_interpretada) pintarInterpretada(cuerpo.consulta_interpretada);
  else interpretada.hidden = true;
  tecnico.replaceChildren(pieTecnico(meta) || "");
  estado.replaceChildren(resumen(meta, r.length));
  // Con resultados, la ayuda larga se pliega (los ejemplos se quedan) y «Resultados» queda a la vista
  if (r.length) document.getElementById("zona-soltar").classList.add("con-resultados");
  mostrarResultados();
  anunciar(r.length ? (r.length === 1 ? "1 resultado" : `${r.length} resultados`) : "Sin resultados");
}

async function buscar(opciones, textoEspera) {
  const miTurno = ++turno;
  interpretada.hidden = true;
  tecnico.replaceChildren();
  resultados.replaceChildren(esqueletos());
  resultados.setAttribute("aria-busy", "true");
  botonBuscar.setAttribute("aria-busy", "true");
  mensaje(estado, textoEspera, "info");
  try {
    const { cuerpo } = await api("/busquedas", { method: "POST", ...opciones });
    if (miTurno === turno) pintar(cuerpo);
  } catch (e) {
    if (miTurno !== turno) return;
    resultados.replaceChildren();
    mensaje(estado, e.message);
  } finally {
    if (miTurno === turno) {
      resultados.removeAttribute("aria-busy");
      botonBuscar.removeAttribute("aria-busy");
    }
  }
}

formularioTexto.addEventListener("submit", (ev) => {
  ev.preventDefault();
  const texto = consulta.value.trim();
  if (texto.length < 2) { mensaje(estado, "Escribe al menos dos caracteres."); return; }
  buscar({ headers: { "Content-Type": "application/json" }, body: JSON.stringify({ texto, k: 12 }) }, `Buscando «${texto}»…`);
});

// Ejemplos: llenan el campo y buscan
for (const boton of document.querySelectorAll(".ejemplo[data-consulta]")) {
  boton.addEventListener("click", () => {
    consulta.value = boton.dataset.consulta;
    formularioTexto.requestSubmit();
  });
}

// «buscar con una foto» despliega el formulario de foto
function mostrarFormularioFoto(abrir) {
  formularioFoto.hidden = !abrir;
  alternarFoto.setAttribute("aria-expanded", String(abrir));
}
alternarFoto.addEventListener("click", () => mostrarFormularioFoto(formularioFoto.hidden));

// La foto elegida se ve como un fotograma suelto sobre la mesa, entera y con sus medidas y su peso, para saber con qué
// se busca. Es una URL local del navegador (no se sube nada hasta pulsar «Buscar parecidas»).
const figuraReferencia = document.getElementById("foto-referencia");
const imagenReferencia = document.getElementById("foto-referencia-img");
const datosReferencia = document.getElementById("foto-referencia-datos");
const peso = (b) => (b >= 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
let urlReferencia = null;

function mostrarReferencia(archivo) {
  if (urlReferencia) URL.revokeObjectURL(urlReferencia);
  urlReferencia = null;
  if (!archivo) {
    figuraReferencia.hidden = true;
    imagenReferencia.removeAttribute("src");
    datosReferencia.textContent = "";
    return;
  }
  urlReferencia = URL.createObjectURL(archivo);
  imagenReferencia.alt = `Foto de referencia: ${archivo.name}`;
  datosReferencia.textContent = peso(archivo.size);
  imagenReferencia.onload = () => {
    datosReferencia.textContent = `${comun.numero(imagenReferencia.naturalWidth)} × ${comun.numero(imagenReferencia.naturalHeight)} px, ${peso(archivo.size)}`;
  };
  imagenReferencia.onerror = () => { figuraReferencia.hidden = true; };
  imagenReferencia.src = urlReferencia;
  figuraReferencia.hidden = false;
}

// El nombre de la foto elegida, junto al botón (el input queda oculto a la vista pero enfocable), y su vista previa
entradaFoto.addEventListener("change", () => {
  document.getElementById("nombre-imagen").textContent = entradaFoto.files[0]?.name || "Ninguna foto elegida";
  mostrarReferencia(entradaFoto.files[0]);
});

formularioFoto.addEventListener("submit", (ev) => {
  ev.preventDefault();
  const archivo = entradaFoto.files[0];
  if (!archivo) { mensaje(estado, "Elige una foto para buscar otras parecidas."); return; }
  const datos = new FormData();
  datos.append("imagen", archivo);
  buscar({ body: datos }, "Buscando fotos parecidas…");
});

// Toda la zona de búsqueda acepta una foto arrastrada
const zona = document.getElementById("zona-soltar");
zona.addEventListener("dragover", (e) => { e.preventDefault(); zona.classList.add("activa"); });
zona.addEventListener("dragleave", (e) => { if (!zona.contains(e.relatedTarget)) zona.classList.remove("activa"); });
zona.addEventListener("drop", (e) => {
  e.preventDefault();
  zona.classList.remove("activa");
  if (!e.dataTransfer.files.length) return;
  mostrarFormularioFoto(true);
  entradaFoto.files = e.dataTransfer.files;
  entradaFoto.dispatchEvent(new Event("change"));
  formularioFoto.requestSubmit();
});

// Llegadas desde Inicio: ?q=… busca al cargar; #con-foto abre la búsqueda por foto
const pedida = new URLSearchParams(location.search).get("q");
if (pedida && pedida.trim().length >= 2) {
  consulta.value = pedida.trim();
  formularioTexto.requestSubmit();
} else if (location.hash === "#con-foto") {
  mostrarFormularioFoto(true);
  entradaFoto.focus();
}
