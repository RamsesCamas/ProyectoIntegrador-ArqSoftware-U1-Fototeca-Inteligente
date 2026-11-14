// Buscar: por texto (POST /api/busquedas JSON) o por foto (multipart). Muestra razones y la consulta interpretada.
import { api, anunciar, el } from "./api.js";
import { mensaje, miniatura, pieTecnico, verFotoGuardada } from "./comun.js";

const estado = document.getElementById("estado");
const resultados = document.getElementById("resultados");
const interpretada = document.getElementById("interpretada");
const tecnico = document.getElementById("tecnico");
const VISIBLES_SIN_DIFERIR = 4;   // la primera fila de resultados carga de inmediato; el resto, al acercarse

function limpiar() {
  resultados.replaceChildren();
  interpretada.hidden = true;
  tecnico.replaceChildren();
}

const puntaje = (p) => (typeof p === "number" ? p.toFixed(2) : p);

function pintar(cuerpo) {
  const r = cuerpo.resultados || [];
  resultados.replaceChildren(...r.map((x, i) => {
    const enlace = `catalogar.html?doc=${encodeURIComponent(x.documento_id)}`;
    const alt = x.texto_alternativo || x.titular || `Resultado ${i + 1} (foto sin ficha)`;
    return el("article", { clase: "tarjeta resultado" },
      // Un clic en la foto la abre en grande con su ficha (visor); el titular lleva a la ficha completa
      el("button", { type: "button", clase: "boton-imagen",
        onclick: () => verFotoGuardada(x.documento_id, { titulo: x.titular || "Resultado de la búsqueda",
          extra: [["Puntaje", puntaje(x.puntaje)], ["Por qué coincide", (x.razones || []).join(" · ")]] }) },
        miniatura(x.documento_id, { alt, diferida: i >= VISIBLES_SIN_DIFERIR }),
        el("span", { clase: "lupa", "aria-hidden": "true", texto: "Ver en grande" }),
        el("span", { clase: "solo-lectores", texto: " (ver en grande)" })),
      el("h3", {}, el("a", { href: enlace, texto: x.titular || x.documento_id })),
      el("p", { clase: "puntaje", texto: `Puntaje ${puntaje(x.puntaje)}` }),
      el("p", { clase: "solo-lectores", texto: "Por qué coincide:" }),
      el("ul", { clase: "razones" }, (x.razones || []).map((razon) => el("li", { texto: razon }))));
  }));
  const q = cuerpo.consulta_interpretada || {};
  if (cuerpo.meta?.ruta === "compleja") {
    interpretada.hidden = false;
    interpretada.replaceChildren(el("div", { clase: "tarjeta" },
      el("h2", { texto: "Así interpreté tu búsqueda" }),
      el("dl", { clase: "interpretada" },
        el("dt", { texto: "Qué debe verse" }), el("dd", { texto: q.consulta_semantica || "—" }),
        el("dt", { texto: "Qué excluir" }), el("dd", { texto: (q.excluir || []).join(", ") || "nada" }),
        el("dt", { texto: "¿Con personas?" }), el("dd", { texto: q.filtros?.contiene_personas === true ? "sí" : q.filtros?.contiene_personas === false ? "no" : "indistinto" }),
        el("dt", { texto: "Términos del tesauro" }), el("dd", { texto: (q.terminos_tesauro || []).join(", ") || "—" }))));
  } else {
    interpretada.hidden = true;
  }
  tecnico.replaceChildren(pieTecnico(cuerpo.meta) || "");
  const texto = r.length ? `${r.length} resultados${cuerpo.meta?.cache && cuerpo.meta.cache !== "ninguna" ? ` (desde la caché ${cuerpo.meta.cache})` : ""}`
    : cuerpo.mensaje || "Sin resultados";
  mensaje(estado, texto, "info");
  anunciar(texto);
}

async function buscar(opciones, textoEspera) {
  limpiar();
  mensaje(estado, textoEspera, "info");
  resultados.setAttribute("aria-busy", "true");
  try {
    const { cuerpo } = await api("/busquedas", { method: "POST", ...opciones });
    pintar(cuerpo);
  } catch (e) {
    mensaje(estado, e.message);
  } finally {
    resultados.removeAttribute("aria-busy");
  }
}

document.getElementById("formulario-texto").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const texto = document.getElementById("consulta").value.trim();
  if (texto.length < 2) { mensaje(estado, "Escribe al menos dos caracteres."); return; }
  buscar({ headers: { "Content-Type": "application/json" }, body: JSON.stringify({ texto, k: 12 }) }, "Buscando…");
});

document.getElementById("formulario-imagen").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const archivo = document.getElementById("imagen").files[0];
  if (!archivo) { mensaje(estado, "Elige una foto para buscar otras parecidas."); return; }
  const datos = new FormData();
  datos.append("imagen", archivo);
  buscar({ body: datos }, "Buscando fotos parecidas…");
});

// Toda la tarjeta de búsqueda acepta una foto arrastrada
const zona = document.getElementById("zona-soltar");
zona.addEventListener("dragover", (e) => { e.preventDefault(); zona.classList.add("activa"); });
zona.addEventListener("dragleave", (e) => { if (!zona.contains(e.relatedTarget)) zona.classList.remove("activa"); });
zona.addEventListener("drop", (e) => {
  e.preventDefault();
  zona.classList.remove("activa");
  if (!e.dataTransfer.files.length) return;
  document.getElementById("imagen").files = e.dataTransfer.files;
  document.getElementById("formulario-imagen").requestSubmit();
});
