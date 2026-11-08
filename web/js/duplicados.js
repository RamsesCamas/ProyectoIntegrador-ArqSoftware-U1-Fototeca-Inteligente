// Duplicados: GET /api/duplicados → grupos de casi duplicados lado a lado, con su similitud.
import { anunciar, api, el } from "./api.js";
import { mensaje } from "./comun.js";

const estado = document.getElementById("estado");
try {
  const { cuerpo: grupos } = await api("/duplicados");
  if (!grupos.length) {
    mensaje(estado, "No se han detectado casi duplicados todavía.", "ok");
  } else {
    const texto = `${grupos.length} ${grupos.length === 1 ? "grupo" : "grupos"} de casi duplicados`;
    mensaje(estado, texto, "ok");
    anunciar(texto);
    document.getElementById("grupos").replaceChildren(...grupos.map((g, i) => el("section", { clase: "tarjeta grupo", "aria-labelledby": `grupo-${i}` },
      el("h2", { id: `grupo-${i}`, texto: `Grupo ${i + 1} · ${g.documentos.length} fotos` }),
      el("ul", { clase: "fila-fotos" }, g.documentos.map((d) => el("li", {},
        el("img", { src: `/api/fotos/${encodeURIComponent(d.id)}/miniatura?lado=256`,
          alt: d.texto_alternativo || `Foto ${d.id} (sin ficha todavía)` }),
        el("p", {}, el("a", { href: `catalogar.html?doc=${encodeURIComponent(d.id)}`, texto: d.titular || d.id })),
        el("p", { clase: "puntaje", texto: `Similitud ${d.similitud}` }),
        d.titular ? el("p", { clase: "id", texto: d.id }) : null))))));
  }
} catch (e) { mensaje(estado, e.message); }
