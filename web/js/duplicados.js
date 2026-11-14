// Duplicados: GET /api/duplicados → grupos de casi duplicados, cada uno en un panel con sus diapositivas lado a lado;
// GET /api/configuracion → el umbral τ_dup (en la descripción del encabezado y en el estado vacío). Sin grupos, un
// estado vacío explica cómo se detectan y cómo provocar uno.
import { anunciar, api, el } from "./api.js";
import { mensaje, miniatura, numero, verFotoGuardada } from "./comun.js";
import { icono, ilustracion } from "./iconos.js";

const EXACTA = 0.9995;   // similitud a partir de la cual dos fotos son la misma imagen (recompresión sin cambios)
const estado = document.getElementById("estado");
const grupos = document.getElementById("grupos");
const descripcion = document.querySelector(".encabezado-descripcion");
const dos = (s) => (typeof s === "number" ? s.toFixed(2) : String(s ?? "—"));

function esqueleto() {
  const diapositiva = () => el("li", { clase: "diapositiva" }, el("span", { clase: "montura" }, el("span", { clase: "esqueleto foto" })),
    el("span", { clase: "esqueleto linea" }));
  grupos.replaceChildren(el("div", { clase: "panel grupo grupo-cargando", "aria-hidden": "true" },
    el("div", { clase: "panel-cabecera" }, el("span", { clase: "esqueleto linea corta" })),
    el("ul", { clase: "panel-cuerpo diapositivas" }, diapositiva(), diapositiva(), diapositiva())));
}

/** Umbral τ_dup en la descripción del encabezado: «… su similitud de imagen llega a τ_dup = 0.95». */
function mostrarUmbral(umbral) {
  if (umbral === null || !descripcion) return;
  descripcion.append(" Se agrupan cuando su similitud de imagen llega al umbral ", el("span", { clase: "umbral", texto: `τ_dup = ${umbral}` }), ".");
}

/** Similitud del grupo: la de sus pares (cada foto trae la mayor con la que entró al grupo). */
function similitudGrupo(docs) {
  const valores = docs.map((d) => d.similitud).filter((s) => typeof s === "number");
  if (!valores.length) return "";
  const min = Math.min(...valores);
  const max = Math.max(...valores);
  const texto = min.toFixed(2) === max.toFixed(2) ? dos(max) : `${dos(min)}–${dos(max)}`;
  return `similitud ${texto} (${min >= EXACTA ? "exacto" : "semántico"})`;
}

function diapositiva(d, diferida) {
  const titulo = d.titular || `Foto ${d.id}`;
  const ficha = `catalogar.html?doc=${encodeURIComponent(d.id)}`;
  return el("li", { clase: "diapositiva" },
    el("figure", { clase: "montura contener" },
      el("button", { type: "button", clase: "boton-imagen",
        onclick: () => verFotoGuardada(d.id, { titulo, extra: [["Similitud en el grupo", dos(d.similitud)]] }) },
        miniatura(d.id, { alt: d.texto_alternativo || `Foto ${d.id} (sin ficha todavía)`, diferida }),
        el("span", { clase: "lupa", "aria-hidden": "true" }, icono("lupa-foto"), "Ver"),
        el("span", { clase: "solo-lectores", texto: " (ver en grande)" })),
      el("figcaption", { clase: "fotograma" }, el("span", { clase: "id", texto: d.id }),
        el("span", { clase: "similitud" }, el("span", { clase: "solo-lectores", texto: "similitud " }), dos(d.similitud)))),
    el("p", { clase: "diapositiva-titular" }, el("a", { href: ficha, texto: d.titular || "Sin ficha todavía: abrir" })));
}

function grupo(g, i) {
  const id = `grupo-${i + 1}`;
  const n = g.documentos.length;
  return el("section", { clase: "panel grupo", "aria-labelledby": id },
    el("header", { clase: "panel-cabecera" }, icono("duplicados"),
      el("h2", { id }, `Grupo ${i + 1} · ${n} ${n === 1 ? "foto" : "fotos"}`,
        el("span", { clase: "grupo-similitud", texto: ` · ${similitudGrupo(g.documentos)}` }))),
    el("ul", { clase: "panel-cuerpo diapositivas" }, g.documentos.map((d) => diapositiva(d, i > 1))));
}

function vacio(umbral) {
  return el("section", { clase: "vacio", "aria-labelledby": "titulo-vacio" },
    ilustracion("duplicados"),
    el("h2", { id: "titulo-vacio", texto: "No hay casi duplicados en el archivo" }),
    el("p", {}, "Al cargar una foto se compara su embedding de imagen con los de las fotos del archivo. Si la similitud llega a ",
      umbral !== null ? el("span", { clase: "umbral", texto: `τ_dup = ${umbral}` }) : "τ_dup", ", las dos fotos aparecen aquí "
      + "juntas, y la ficha de la nueva avisa «Posible duplicado de…»."),
    el("div", { clase: "vacio-pasos" },
      el("p", { clase: "vacio-pasos-titulo", texto: "Para provocar uno:" }),
      el("ol", {},
        el("li", { texto: "Cataloga una foto que todavía no esté en el archivo." }),
        el("li", { texto: "Sube después una copia recortada (o recomprimida) de esa misma foto." }),
        el("li", { texto: "Vuelve a esta página: las dos aparecen en un grupo, con su similitud." }))),
    el("a", { clase: "boton secundario", href: "catalogar.html" }, icono("subir"), "Catalogar fotos"));
}

esqueleto();
const [listado, configuracion] = await Promise.allSettled([api("/duplicados"), api("/configuracion")]);
const umbral = configuracion.status === "fulfilled" ? configuracion.value.cuerpo?.parametros?.cache?.fichas?.tau_dup ?? null : null;
mostrarUmbral(umbral);
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
    const texto = `${numero(lista.length)} ${lista.length === 1 ? "grupo" : "grupos"} · ${numero(fotos)} fotos casi duplicadas`;
    estado.replaceChildren(el("p", { clase: "resumen-grupos" }, icono("duplicados"), texto));
    grupos.replaceChildren(...lista.map(grupo));
    anunciar(texto);
  }
}
