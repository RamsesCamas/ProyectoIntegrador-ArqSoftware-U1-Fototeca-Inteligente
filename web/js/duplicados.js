// Duplicados: GET /api/duplicados → grupos de casi duplicados lado a lado, con su similitud. Sin grupos, un estado
// vacío explica cómo se detectan y cómo provocar uno (el umbral sale de GET /api/configuracion, si responde).
import { anunciar, api, el } from "./api.js";
import { mensaje, miniatura, verFotoGuardada } from "./comun.js";

const estado = document.getElementById("estado");
const grupos = document.getElementById("grupos");
const similitud = (s) => (typeof s === "number" ? s.toFixed(2) : s);

async function estadoVacio() {
  let umbral = null;
  try {
    const { cuerpo } = await api("/configuracion");
    umbral = cuerpo?.parametros?.cache?.fichas?.tau_dup ?? null;
  } catch { /* sin umbral: la explicación no lo cita */ }
  grupos.replaceChildren(el("section", { clase: "tarjeta estado-vacio", "aria-labelledby": "titulo-vacio" },
    el("h2", { id: "titulo-vacio", texto: "Todavía no hay casi duplicados" }),
    el("p", {}, "Al cargar una foto, el servicio compara su embedding de imagen con el de las fotos del archivo. ",
      umbral !== null ? `Si la similitud llega a ${umbral} (τ_dup) o más, ` : "Si la similitud llega al umbral τ_dup, ",
      "registra la pareja como casi duplicado y aquí aparecen juntas. Si la original ya tiene ficha, se reutiliza y la "
      + "nueva ficha avisa «Posible duplicado de…»."),
    el("p", { texto: "Para ver uno:" }),
    el("ol", {},
      el("li", {}, "En ", el("a", { href: "catalogar.html", texto: "Catalogar" }), ", sube una foto que no esté en el archivo y espera su ficha."),
      el("li", { texto: "Sube después una copia recortada o recomprimida de esa misma foto." }),
      el("li", { texto: "Vuelve a esta página: las dos fotos aparecen juntas, con su similitud." }))));
}

try {
  const { cuerpo: lista } = await api("/duplicados");
  if (!lista.length) {
    await estadoVacio();
    anunciar("No se han detectado casi duplicados todavía.");
  } else {
    const texto = `${lista.length} ${lista.length === 1 ? "grupo" : "grupos"} de casi duplicados`;
    mensaje(estado, texto, "info");
    anunciar(texto);
    grupos.replaceChildren(...lista.map((g, i) => el("section", { clase: "tarjeta grupo", "aria-labelledby": `grupo-${i}` },
      el("h2", { id: `grupo-${i}`, texto: `Grupo ${i + 1} · ${g.documentos.length} fotos` }),
      el("ul", { clase: "fila-fotos" }, g.documentos.map((d) => el("li", {},
        el("button", { type: "button", clase: "boton-imagen",
          onclick: () => verFotoGuardada(d.id, { titulo: d.titular || `Foto ${d.id}`, extra: [["Similitud", similitud(d.similitud)]] }) },
          miniatura(d.id, { alt: d.texto_alternativo || `Foto ${d.id} (sin ficha todavía)`, diferida: i > 1 }),
          el("span", { clase: "lupa", "aria-hidden": "true", texto: "Ver" }),
          el("span", { clase: "solo-lectores", texto: " (ver en grande)" })),
        el("p", {}, el("a", { href: `catalogar.html?doc=${encodeURIComponent(d.id)}`, texto: d.titular || d.id })),
        el("p", { clase: "puntaje", texto: `Similitud ${similitud(d.similitud)}` }),
        d.titular ? el("p", { clase: "id", texto: d.id }) : null))))));
  }
} catch (e) { mensaje(estado, e.message); }
