// Iconos de Fototeca Viva: un sprite de símbolos SVG ORIGINALES (dibujados para este proyecto, no copiados de ninguna
// biblioteca) en una retícula de 24, con trazo de 1.75, puntas y uniones redondeadas, sin relleno y en currentColor
// (el color lo da el texto que acompañan; los colores viven en css/base.css). El sprite se inyecta una sola vez por
// página al importar este módulo; `icono(nombre)` devuelve
//   <svg class="icono" aria-hidden="true" focusable="false"><use href="#i-nombre"/></svg>
// Los iconos son decorativos: el texto de al lado (o un aria-label) siempre dice lo mismo.

const SVG = "http://www.w3.org/2000/svg";

/** Trazos de cada icono (contenido de un <symbol viewBox="0 0 24 24">). */
const TRAZOS = {
  // Módulos (navegación)
  inicio: '<path d="M3.5 10.5 12 3.75l8.5 6.75"/><path d="M5.75 9v10.25c0 .55.45 1 1 1h10.5c.55 0 1-.45 1-1V9"/><path d="M10 20.25v-5.5h4v5.5"/>',
  catalogar: '<rect x="3" y="4.5" width="18" height="15" rx="2"/><rect x="6" y="8" width="5" height="5" rx="1"/><path d="M14 9h4M14 12h4M6 16h12"/>',
  buscar: '<circle cx="10.5" cy="10.5" r="6.25"/><path d="m15.25 15.25 5.25 5.25"/>',
  duplicados: '<rect x="8" y="8" width="12.5" height="12.5" rx="2"/><path d="M16 8V5.5c0-1.1-.9-2-2-2H5.5c-1.1 0-2 .9-2 2V14c0 1.1.9 2 2 2H8"/>',
  archivo: '<rect x="3" y="4" width="18" height="4.5" rx="1"/><path d="M4.75 8.5v9.75c0 1.1.9 2 2 2h10.5c1.1 0 2-.9 2-2V8.5"/><path d="M10 12.5h4"/>',
  metricas: '<path d="M4 4v14.5c0 .83.67 1.5 1.5 1.5H20"/><path d="M8.5 16v-4M12.5 16V8M16.5 16v-6"/>',
  // Fotos
  foto: '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="15.5" cy="9.5" r="1.5"/><path d="m3.5 16.5 4.5-4.5 4 4 2.5-2.5 5.75 5.75"/>',
  subir: '<path d="M12 15.5v-11"/><path d="M7.5 9 12 4.5 16.5 9"/><path d="M4 15v3c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2v-3"/>',
  "lupa-foto": '<path d="M11.5 18H5c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2h12c1.1 0 2 .9 2 2v5"/><path d="m3.5 14.5 4-4 3.5 3.5"/><circle cx="16.5" cy="16.5" r="3.25"/><path d="m18.9 18.9 2.1 2.1"/>',
  // Tipos de fuente (trazabilidad)
  regla: '<g transform="rotate(-45 12 12)"><rect x="2.5" y="8.5" width="19" height="7" rx="1.5"/><path d="M6.5 8.5v2.75M10 8.5v3.75M13.5 8.5v2.75M17 8.5v3.75"/></g>',
  tesauro: '<rect x="3" y="3.5" width="8" height="4.5" rx="1"/><rect x="12" y="10" width="9" height="4.5" rx="1"/><rect x="12" y="16.5" width="9" height="4.5" rx="1"/><path d="M7 8v10.75h5M7 12.25h5"/>',
  "foto-similar": '<path d="M12 18H5c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2h12c1.1 0 2 .9 2 2v5.5"/><path d="m3.5 14.5 4-4 3.5 3.5"/><path d="M14.5 16.25c1.1-.8 2.15-.8 3.25 0s2.15.8 3.25 0M14.5 20.25c1.1-.8 2.15-.8 3.25 0s2.15.8 3.25 0"/>',
  archivista: '<circle cx="9" cy="7.5" r="3.5"/><path d="M3 20c0-3.31 2.69-6 6-6 1.16 0 2.25.33 3.17.9"/><path d="m14.5 20.5.6-2.9 5.15-5.15a1.6 1.6 0 0 1 2.3 2.3L17.4 19.9z"/>',
  referencia: '<path d="M4.5 4.5h15c.83 0 1.5.67 1.5 1.5v9c0 .83-.67 1.5-1.5 1.5H10.5L6 20v-3.5H4.5c-.83 0-1.5-.67-1.5-1.5V6c0-.83.67-1.5 1.5-1.5z"/><path d="M7 9h10M7 12.5h6.5"/>',
  etiqueta: '<path d="M3.5 11.6V5.5c0-1.1.9-2 2-2h6.1c.53 0 1.04.21 1.41.59l7.4 7.4c.78.78.78 2.05 0 2.83l-6.1 6.1c-.78.78-2.05.78-2.83 0l-7.4-7.4c-.37-.37-.58-.88-.58-1.42z"/><circle cx="8.25" cy="8.25" r="1.5"/>',
  // Capas de la tubería
  escudo: '<path d="M12 3.5 19 6v5.5c0 4.4-2.9 7.9-7 9.25-4.1-1.35-7-4.85-7-9.25V6z"/>',
  "escudo-check": '<path d="M12 3.5 19 6v5.5c0 4.4-2.9 7.9-7 9.25-4.1-1.35-7-4.85-7-9.25V6z"/><path d="m9 12.25 2.25 2.25 4.25-4.5"/>',
  rayo: '<path d="M13.5 3 5.5 13.5h6l-1 7.5 8-10.5h-6z"/>',
  libros: '<rect x="3" y="4.5" width="4.5" height="15.5" rx="1"/><rect x="9" y="7" width="4.5" height="13" rx="1"/><rect x="15" y="7" width="4" height="13" rx="1" transform="rotate(12 15 20)"/>',
  bifurcacion: '<path d="M3.5 12h5"/><path d="M8.5 12c2.6 0 3.4-5 7-5h4"/><path d="M8.5 12c2.6 0 3.4 5 7 5h4"/><path d="m17 4.5 2.5 2.5-2.5 2.5M17 14.5l2.5 2.5-2.5 2.5"/>',
  ojo: '<path d="M2.75 12C4.6 8.2 8 6 12 6s7.4 2.2 9.25 6C19.4 15.8 16 18 12 18s-7.4-2.2-9.25-6z"/><circle cx="12" cy="12" r="2.75"/>',
  pluma: '<path d="m4.5 19.5 3.25-9 6-6.25 6 6-6.25 6z"/><path d="m4.5 19.5 6.25-6.25"/><circle cx="12" cy="12" r="1.5"/>',
  // Estados y acciones
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  alerta: '<path d="M10.27 4.5 2.9 17.25c-.77 1.33.19 3 1.73 3h14.74c1.54 0 2.5-1.67 1.73-3L13.73 4.5c-.77-1.33-2.69-1.33-3.46 0z"/><path d="M12 9.5v4.25"/><path d="M12 17h.01" stroke-width="2.5"/>',
  info: '<circle cx="12" cy="12" r="8.75"/><path d="M12 11v5.25"/><path d="M12 7.75h.01" stroke-width="2.5"/>',
  error: '<circle cx="12" cy="12" r="8.75"/><path d="m9.25 9.25 5.5 5.5M14.75 9.25l-5.5 5.5"/>',
  externo: '<path d="M14 4h6v6"/><path d="m20 4-8.5 8.5"/><path d="M18 13.5V18c0 1.1-.9 2-2 2H6c-1.1 0-2-.9-2-2V8c0-1.1.9-2 2-2h4.5"/>',
  reloj: '<circle cx="12" cy="12" r="8.75"/><path d="M12 7.25V12l3.25 2"/>',
  cerrar: '<path d="m6 6 12 12M18 6 6 18"/>',
  papelera: '<path d="M4 7h16"/><path d="M9.5 7V5c0-.55.45-1 1-1h3c.55 0 1 .45 1 1v2"/><path d="m6 7 .9 12.1c.08 1.05.95 1.9 2 1.9h6.2c1.05 0 1.92-.85 2-1.9L18 7"/><path d="M10 11v6M14 11v6"/>',
  servidor: '<rect x="3.5" y="4" width="17" height="7" rx="1.5"/><rect x="3.5" y="13" width="17" height="7" rx="1.5"/><path d="M7.5 7.5h.01M7.5 16.5h.01" stroke-width="2.5"/><path d="M11 7.5h5.5M11 16.5h5.5"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="1.5"/><rect x="9.5" y="9.5" width="5" height="5" rx=".5"/><path d="M9.5 3v3M14.5 3v3M9.5 18v3M14.5 18v3M3 9.5h3M3 14.5h3M18 9.5h3M18 14.5h3"/>',
  "base-datos": '<ellipse cx="12" cy="6" rx="7.5" ry="2.75"/><path d="M4.5 6v12c0 1.52 3.36 2.75 7.5 2.75s7.5-1.23 7.5-2.75V6"/><path d="M4.5 12c0 1.52 3.36 2.75 7.5 2.75s7.5-1.23 7.5-2.75"/>',
  "sin-red": '<path d="M7.25 18.5h10a3.75 3.75 0 0 0 .7-7.43A5.5 5.5 0 0 0 7.4 9.7a4.4 4.4 0 0 0-.15 8.8z"/><path d="m3.5 3.5 17 17"/>',
  flecha: '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
  mas: '<path d="M12 5v14M5 12h14"/>',
  chevron: '<path d="m9.5 6 6 6-6 6"/>',
  actualizar: '<path d="M19.5 10A7.75 7.75 0 0 0 5.6 7.4"/><path d="M5 3.75V7.9h4.15"/><path d="M4.5 14a7.75 7.75 0 0 0 13.9 2.6"/><path d="M19 20.25V16.1h-4.15"/>',
};

/** Ilustraciones para los estados vacíos (contenido de un <symbol viewBox="0 0 120 96">). La clase acento-trazo usa
 *  el color de acento (base.css); lo demás, el color del texto. */
const ILUSTRACIONES = {
  // Una diapositiva vacía sobre la mesa de luz
  vacio: '<rect x="30" y="14" width="60" height="60" rx="6"/><rect x="40" y="28" width="40" height="28" rx="2"/>'
    + '<path d="M22 84h76" class="acento-trazo"/><path d="M45 50l8-8 6 6 5-5 11 11"/>',
  // Dos marcos superpuestos y una lupa (Duplicados)
  duplicados: '<rect x="16" y="14" width="50" height="50" rx="5"/><rect x="24.5" y="26" width="33" height="23" rx="2"/>'
    + '<rect x="42" y="28" width="50" height="50" rx="5"/><rect x="50.5" y="40" width="33" height="23" rx="2"/>'
    + '<circle cx="86" cy="64" r="13" class="acento-trazo"/><path d="m95.5 73.5 10 10" class="acento-trazo"/>',
  // Una lupa sobre una hoja de contactos (Buscar sin resultados)
  busqueda: '<rect x="14" y="18" width="24" height="18" rx="2"/><rect x="44" y="18" width="24" height="18" rx="2"/>'
    + '<rect x="14" y="44" width="24" height="18" rx="2"/><rect x="44" y="44" width="24" height="18" rx="2"/>'
    + '<circle cx="82" cy="54" r="16" class="acento-trazo"/><path d="m94 66 12 12" class="acento-trazo"/>',
};

export const ICONOS = Object.freeze(Object.keys(TRAZOS));

// El grosor NO va en el símbolo: lo hereda del CSS (.icono 1.75, .icono-48 1.5, .insignia 2.25, .vacio-ilustracion 2).
const ATRIBUTOS_TRAZO = 'fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"';

function crearSprite() {
  const sprite = document.createElementNS(SVG, "svg");
  sprite.setAttribute("class", "sprite");
  sprite.setAttribute("aria-hidden", "true");
  sprite.setAttribute("focusable", "false");
  sprite.id = "sprite-iconos";
  sprite.innerHTML = Object.entries(TRAZOS)
    .map(([n, d]) => `<symbol id="i-${n}" viewBox="0 0 24 24" ${ATRIBUTOS_TRAZO}>${d}</symbol>`).join("")
    + Object.entries(ILUSTRACIONES)
      .map(([n, d]) => `<symbol id="il-${n}" viewBox="0 0 120 96" ${ATRIBUTOS_TRAZO}>${d}</symbol>`).join("");
  return sprite;
}

/** Inyecta el sprite una sola vez (idempotente). Se llama al importar el módulo. */
export function inyectarSprite() {
  if (document.getElementById("sprite-iconos")) return;
  const poner = () => { if (!document.getElementById("sprite-iconos")) document.body.prepend(crearSprite()); };
  if (document.body) poner();
  else document.addEventListener("DOMContentLoaded", poner, { once: true });
}

function usar(id, clase) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("class", clase);
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const use = document.createElementNS(SVG, "use");
  use.setAttribute("href", `#${id}`);
  svg.append(use);
  return svg;
}

/** Icono decorativo del sprite: `icono("buscar")`, `icono("check", "icono-16")`. */
export function icono(nombre, clase = "") {
  if (!(nombre in TRAZOS)) console.warn(`Icono desconocido: ${nombre}`);
  return usar(`i-${nombre}`, `icono${clase ? ` ${clase}` : ""}`);
}

/** Ilustración de estado vacío: `ilustracion("duplicados")`. */
export function ilustracion(nombre, clase = "") {
  if (!(nombre in ILUSTRACIONES)) console.warn(`Ilustración desconocida: ${nombre}`);
  return usar(`il-${nombre}`, `vacio-ilustracion${clase ? ` ${clase}` : ""}`);
}

inyectarSprite();
