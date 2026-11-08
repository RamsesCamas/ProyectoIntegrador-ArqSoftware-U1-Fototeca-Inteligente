// Buscar: por texto (POST /api/busquedas JSON) o por foto (multipart). Muestra razones y la consulta interpretada.
import { api, anunciar, el } from "./api.js";
import { mensaje, pieTecnico } from "./comun.js";

const estado = document.getElementById("estado");
const resultados = document.getElementById("resultados");
const interpretada = document.getElementById("interpretada");
const tecnico = document.getElementById("tecnico");

function limpiar() {
  resultados.replaceChildren();
  interpretada.hidden = true;
  tecnico.replaceChildren();
}

function pintar(cuerpo) {
  const r = cuerpo.resultados || [];
  resultados.replaceChildren(...r.map((x, i) => {
    const enlace = `catalogar.html?doc=${encodeURIComponent(x.documento_id)}`;
    return el("article", { clase: "tarjeta resultado" },
      el("img", { src: x.miniatura_url, alt: x.texto_alternativo || x.titular || `Resultado ${i + 1} (foto sin ficha)` }),
      el("h3", {}, el("a", { href: enlace, texto: x.titular || x.documento_id })),
      el("p", { clase: "puntaje", texto: `Puntaje ${x.puntaje}` }),
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
  mensaje(estado, texto, "ok");
  anunciar(texto);
}

async function buscar(opciones, textoEspera) {
  limpiar();
  mensaje(estado, textoEspera, "ok");
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

const zona = document.getElementById("zona-soltar");
zona.addEventListener("dragover", (e) => { e.preventDefault(); zona.classList.add("activa"); });
zona.addEventListener("dragleave", () => zona.classList.remove("activa"));
zona.addEventListener("drop", (e) => {
  e.preventDefault();
  zona.classList.remove("activa");
  document.getElementById("imagen").files = e.dataTransfer.files;
  document.getElementById("formulario-imagen").requestSubmit();
});
