// Duplicados: GET /api/duplicados → cada grupo de casi duplicados es una tira de película corta (ol.tira): la foto de
// referencia (la primera) va circulada con el lápiz graso (.cuadro.marcado) y las demás llevan su similitud en mono; el
// titular va bajo cada fotograma (.cuadro-pie). GET /api/configuracion → el umbral τ_dup (en la descripción del
// encabezado y en el estado vacío, que va en prosa). La API no tiene acción para conservar una versión: solo se compara.
import { anunciar, api, el } from "./api.js";
import * as comun from "./comun.js";

const { mensaje, miniatura, numero, verFotoGuardada } = comun;
const EXACTA = 0.9995;   // similitud a partir de la cual dos fotos son la misma imagen (recompresión sin cambios)
const NUMEROS = ["", "una", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve"];
const estado = document.getElementById("estado");
const grupos = document.getElementById("grupos");
const descripcion = document.querySelector(".encabezado-descripcion");
const dos = (s) => (typeof s === "number" ? s.toFixed(2) : String(s ?? "—"));
/** El trazo del lápiz graso (comun.js · marcaLapiz); si la base todavía no lo trae, la marca queda solo en el texto. */
const lapiz = (tipo) => (typeof comun.marcaLapiz === "function" ? comun.marcaLapiz(tipo) : null);

function esqueleto() {
  const cuadro = () => el("li", { clase: "cuadro" }, el("span", { clase: "cuadro-foto" }, el("span", { clase: "esqueleto foto" })));
  grupos.replaceChildren(el("section", { clase: "panel grupo grupo-cargando", "aria-hidden": "true" },
    el("span", { clase: "esqueleto linea corta" }),
    el("ol", { clase: "tira tira-corta" }, cuadro(), cuadro(), cuadro())));
}

/** Descripción del encabezado: agrega el umbral τ_dup actual (el texto base está en el HTML). */
function ajustarDescripcion(umbral) {
  if (!descripcion || umbral === null) return;
  descripcion.append(" Se agrupan cuando su similitud de imagen llega a ", el("span", { clase: "umbral", texto: `τ_dup = ${umbral}` }), ".");
}

/** Resumen del grupo en prosa: cuántas fotos y su similitud con la referencia. */
function resumenGrupo(docs) {
  const n = docs.length;
  const otras = docs.slice(1).map((d) => d.similitud).filter((s) => typeof s === "number");
  const cuantas = `${NUMEROS[n] ? NUMEROS[n][0].toUpperCase() + NUMEROS[n].slice(1) : numero(n)} fotos casi iguales`;
  if (!otras.length) return `${cuantas}.`;
  const min = Math.min(...otras);
  const max = Math.max(...otras);
  const rango = min.toFixed(2) === max.toFixed(2) ? dos(max) : `de ${dos(min)} a ${dos(max)}`;
  return [`${cuantas}: similitud de imagen `, el("span", { clase: "cifra", texto: rango }),
    ` con la referencia, circulada (${min >= EXACTA ? "copia exacta" : "parecido semántico"}).`];
}

/** Fotograma de la tira: la referencia (posición 0) circulada; las demás, con su similitud en el número de cuadro. */
function cuadro(d, posicion, diferida) {
  const titulo = d.titular || `Foto ${d.id}`;
  const referencia = posicion === 0;
  return el("li", { clase: `cuadro${referencia ? " marcado" : ""}` },
    el("button", { type: "button", clase: "cuadro-foto",
      onclick: () => verFotoGuardada(d.id, { titulo, extra: [["Similitud en el grupo", dos(d.similitud)]] }) },
      miniatura(d.id, { alt: d.texto_alternativo || `Foto ${d.id} (sin ficha todavía)`, lado: 256, ancho: 256, alto: 192, diferida }),
      el("span", { clase: "solo-lectores", texto: referencia ? " (referencia del grupo; ver en grande)" : " (ver en grande)" }),
      // El círculo del lápiz va sobre la foto (el .cuadro-foto es su padre posicionado)
      referencia ? lapiz("circulo") : null),
    referencia
      ? el("span", { clase: "cuadro-num cuadro-referencia", texto: "Referencia" })
      : el("span", { clase: "cuadro-num" }, el("span", { clase: "solo-lectores", texto: "similitud " }), dos(d.similitud)),
    el("div", { clase: "cuadro-pie" },
      el("p", { clase: "cuadro-titular" }, el("a", { href: `catalogar.html?doc=${encodeURIComponent(d.id)}`, texto: d.titular || "Sin ficha todavía" })),
      el("p", { clase: "cuadro-id" }, el("span", { clase: "id", title: d.id, texto: d.id }))));
}

function grupo(g, i) {
  const id = `grupo-${i + 1}`;
  return el("section", { clase: "panel grupo", "aria-labelledby": id },
    el("h2", { id, texto: `Grupo ${i + 1}` }),
    el("p", { clase: "grupo-resumen" }, resumenGrupo(g.documentos)),
    el("ol", { clase: "tira tira-corta", "aria-label": `Fotos del grupo ${i + 1}` }, g.documentos.map((d, j) => cuadro(d, j, i > 1))));
}

function vacio(umbral) {
  return el("section", { clase: "panel vacio-duplicados", "aria-labelledby": "titulo-vacio" },
    el("h2", { id: "titulo-vacio", texto: "No hay casi duplicados en el archivo" }),
    el("p", {}, "Al cargar una foto, el servicio compara su embedding de imagen con los de las fotos del archivo. Si la similitud llega a ",
      umbral !== null ? el("span", { clase: "umbral", texto: `τ_dup = ${umbral}` }) : "τ_dup",
      ", las dos fotos aparecen aquí en una tira, con la original circulada, y la ficha de la nueva avisa «Posible duplicado de…»."),
    el("h3", { texto: "Cómo probarlo" }),
    el("ol", { clase: "pasos" },
      el("li", { texto: "Cataloga una foto que todavía no esté en el archivo." }),
      el("li", { texto: "Sube después una copia recortada (o recomprimida) de esa misma foto." }),
      el("li", { texto: "Vuelve a esta página: las dos aparecen en un grupo, con su similitud." })),
    el("p", {}, el("a", { clase: "boton primario", href: "catalogar.html", texto: "Catalogar una foto" })));
}

esqueleto();
const [listado, configuracion] = await Promise.allSettled([api("/duplicados"), api("/configuracion")]);
const umbral = configuracion.status === "fulfilled" ? configuracion.value.cuerpo?.parametros?.cache?.fichas?.tau_dup ?? null : null;
ajustarDescripcion(umbral);
if (listado.status === "rejected") {
  grupos.replaceChildren();
  mensaje(estado, listado.reason.message);
} else {
  const lista = listado.value.cuerpo || [];
  if (!lista.length) {
    grupos.replaceChildren(vacio(umbral));
    anunciar("No hay casi duplicados en el archivo.");
  } else {
    const fotos = lista.reduce((s, g) => s + g.documentos.length, 0);
    const texto = `${numero(lista.length)} ${lista.length === 1 ? "grupo" : "grupos"} con ${numero(fotos)} fotos casi duplicadas.`;
    estado.replaceChildren(el("p", { clase: "resumen-grupos", texto }));
    grupos.replaceChildren(...lista.map(grupo));
    anunciar(texto);
  }
}
