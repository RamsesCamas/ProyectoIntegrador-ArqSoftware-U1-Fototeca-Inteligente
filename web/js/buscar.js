// Buscar: por texto (POST /api/busquedas JSON) o por foto (multipart). Cada resultado es una diapositiva que abre el
// visor, con su rango y las razones por las que coincide (con sus similitudes); la consulta interpretada aparece cuando la
// búsqueda fue compleja (la descompuso el modelo de lenguaje). La línea de #estado dice cuántos, por qué ruta y en
// cuánto tiempo; el pie técnico, el resto.
import { api, anunciar, el } from "./api.js";
import { crearMensaje, mensaje, miniatura, numero, pieTecnico, segundos, verFotoGuardada } from "./comun.js";
import { icono, ilustracion } from "./iconos.js";

const estado = document.getElementById("estado");
const resultados = document.getElementById("resultados");
const interpretada = document.getElementById("interpretada");
const tecnico = document.getElementById("tecnico");
const consulta = document.getElementById("consulta");
const formularioTexto = document.getElementById("formulario-texto");
const formularioFoto = document.getElementById("formulario-imagen");
const alternarFoto = document.getElementById("alternar-foto");
const botonBuscar = formularioTexto.querySelector("button[type=submit]");
const VISIBLES_SIN_DIFERIR = 8;   // las dos primeras filas cargan de inmediato; el resto, al acercarse
let turno = 0;                    // solo pinta la respuesta de la búsqueda más reciente

const RUTAS = { simple: "ruta simple", compleja: "ruta compleja", imagen: "búsqueda por foto" };
const esPenalizacion = (razon) => /^penaliz/i.test(razon);

/** Icono de cada razón según de dónde sale la coincidencia (el texto de la razón siempre lo dice). */
function iconoRazon(razon) {
  if (esPenalizacion(razon)) return "alerta";
  if (/imagen\s*→\s*imagen|foto parecida|imagen parecida/i.test(razon)) return "foto-similar";
  if (/imagen/i.test(razon)) return "ojo";
  if (/tesauro/i.test(razon)) return "tesauro";
  if (/ficha/i.test(razon)) return "catalogar";
  return "check";
}

function tarjeta(x, i) {
  const titular = x.titular || "Foto sin ficha";
  const alt = x.texto_alternativo || x.titular || `Resultado ${i + 1} (foto sin ficha)`;
  const idTitular = `resultado-${i + 1}`;
  const razones = x.razones || [];
  return el("article", { clase: "resultado", "aria-labelledby": idTitular },
    // La diapositiva abre la foto en grande con su ficha (visor); el titular lleva a la ficha completa
    el("button", { type: "button", clase: "boton-imagen resultado-foto",
      onclick: () => verFotoGuardada(x.documento_id, { titulo: titular,
        extra: [["Posición", `#${i + 1}`], ["Por qué coincide", razones.join(" · ")]] }) },
      miniatura(x.documento_id, { alt, diferida: i >= VISIBLES_SIN_DIFERIR }),
      el("span", { clase: "lupa", "aria-hidden": "true" }, icono("lupa-foto"), "Ver en grande"),
      el("span", { clase: "solo-lectores", texto: " (ver en grande con su ficha)" })),
    // Solo el rango: el orden sale de fusionar dos listas (RRF) con penalizaciones, y `puntaje` de la API es solo la
    // similitud texto→imagen, que ya aparece en las razones. Mostrarlo como insignia junto al rango parecía un
    // puntaje de orden que no cuadra (#1 con 0.70 sobre #3 con 0.73).
    el("div", { clase: "resultado-meta" },
      el("span", { clase: "rango" }, el("span", { clase: "solo-lectores", texto: "Posición " }), `#${i + 1}`)),
    el("h3", { clase: "resultado-titular", id: idTitular },
      el("a", { href: `catalogar.html?doc=${encodeURIComponent(x.documento_id)}`, title: titular, texto: titular })),
    el("p", { clase: "solo-lectores", texto: "Por qué coincide:" }),
    el("ul", { clase: "razones" }, razones.map((razon) => el("li", { clase: esPenalizacion(razon) ? "penalizada" : null },
      icono(iconoRazon(razon)), el("span", { texto: razon })))));
}

/** Marcadores mientras llega la respuesta (div, no article: no son resultados). */
const esqueletos = (n = 8) => Array.from({ length: n }, () => el("div", { clase: "resultado cargando", "aria-hidden": "true" },
  el("span", { clase: "esqueleto foto" }), el("span", { clase: "esqueleto linea corta" }), el("span", { clase: "esqueleto linea" }),
  el("span", { clase: "esqueleto linea" })));

/** Línea de resultados: cuántos · ruta · tiempo · caché (es el .mensaje de #estado cuando la búsqueda termina). */
function resumen(meta, n) {
  const partes = [
    el("strong", { texto: n === 1 ? "1 resultado" : `${numero(n)} resultados` }),
    RUTAS[meta.ruta] || (meta.ruta ? `ruta ${meta.ruta}` : null),
    typeof meta.tiempo_ms === "number" ? el("span", { clase: "mono", texto: segundos(meta.tiempo_ms) }) : null,
    meta.cache && meta.cache !== "ninguna" ? `desde la caché (${meta.cache})` : null,
  ].filter(Boolean);
  const linea = crearMensaje(partes.flatMap((p, k) => (k ? [el("span", { clase: "separador", "aria-hidden": "true", texto: "·" }), p] : [p])),
    n ? "ok" : "info");
  linea.classList.add("resumen");
  return linea;
}

const par = (termino, valor) => el("div", {}, el("dt", { texto: termino }), el("dd", {}, valor));

function pintarInterpretada(q) {
  const personas = q.filtros?.contiene_personas;
  const terminos = q.terminos_tesauro || [];
  interpretada.replaceChildren(
    el("header", { clase: "panel-cabecera" }, icono("bifurcacion"),
      el("h2", { id: "titulo-interpretada", texto: "Consulta interpretada" }),
      el("p", { clase: "panel-auxiliar", texto: "Así la descompuso el modelo de lenguaje" })),
    el("dl", { clase: "interpretada" },
      par("Qué debe verse", q.consulta_semantica || "—"),
      par("Qué excluir", (q.excluir || []).join(", ") || "Nada"),
      par("¿Con personas?", personas === true ? "Sí" : personas === false ? "No" : "Indistinto"),
      par("Términos del tesauro", terminos.length
        ? el("ul", { clase: "interpretada-chips" }, terminos.map((t) => el("li", {}, el("span", { clase: "chip chip-tesauro" }, icono("tesauro"), t))))
        : "—")));
  interpretada.hidden = false;
}

function pintar(cuerpo) {
  const r = cuerpo.resultados || [];
  const meta = cuerpo.meta || {};
  resultados.replaceChildren(...(r.length ? r.map(tarjeta) : [el("div", { clase: "vacio" }, ilustracion("busqueda"),
    el("h3", { texto: "Sin resultados" }),
    el("p", { texto: cuerpo.mensaje || "Ninguna foto del archivo coincide lo suficiente. Prueba con otras palabras, con menos condiciones o con una foto parecida." }))]));
  if (meta.ruta === "compleja" && cuerpo.consulta_interpretada) pintarInterpretada(cuerpo.consulta_interpretada);
  else interpretada.hidden = true;
  tecnico.replaceChildren(pieTecnico(meta) || "");
  estado.replaceChildren(resumen(meta, r.length));
  anunciar(r.length ? `${r.length === 1 ? "1 resultado" : `${r.length} resultados`}` : "Sin resultados");
}

async function buscar(opciones, textoEspera) {
  const miTurno = ++turno;
  interpretada.hidden = true;
  tecnico.replaceChildren();
  resultados.replaceChildren(...esqueletos());
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
for (const boton of document.querySelectorAll(".ejemplo")) {
  boton.addEventListener("click", () => {
    consulta.value = boton.dataset.consulta;
    formularioTexto.requestSubmit();
  });
}

// «O busca con una foto» despliega el formulario de foto
function mostrarFormularioFoto(abrir) {
  formularioFoto.hidden = !abrir;
  alternarFoto.setAttribute("aria-expanded", String(abrir));
}
alternarFoto.addEventListener("click", () => mostrarFormularioFoto(formularioFoto.hidden));

// El nombre de la foto elegida, junto al botón (el input queda oculto a la vista pero enfocable)
const entradaFoto = document.getElementById("imagen");
entradaFoto.addEventListener("change", () => {
  document.getElementById("nombre-imagen").textContent = entradaFoto.files[0]?.name || "Ninguna foto elegida";
});

formularioFoto.addEventListener("submit", (ev) => {
  ev.preventDefault();
  const archivo = entradaFoto.files[0];
  if (!archivo) { mensaje(estado, "Elige una foto para buscar otras parecidas."); return; }
  const datos = new FormData();
  datos.append("imagen", archivo);
  buscar({ body: datos }, "Buscando fotos parecidas…");
});

// Todo el panel de búsqueda acepta una foto arrastrada
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
