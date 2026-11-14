// Shell de las 6 páginas (cabecera «Mesa de luz»): inyecta el sprite de iconos y mantiene al día el estado de la
// derecha (un punto más el texto «Todo local, en verde») con GET /api/health al cargar y cada 60 s, en pausa mientras la
// pestaña está oculta. No usa ids de las páginas (Inicio tiene su propio estado) y solo cambia el DOM cuando cambia el
// estado: no es una región viva, para no repetir avisos en los lectores de pantalla (Inicio ya anuncia los cambios).
import { api } from "./api.js";
import "./iconos.js";

const INTERVALO_MS = 60_000;
const punto = document.querySelector(".estado-local .punto-estado");
const texto = document.querySelector(".estado-local-texto");
// estado de /health → [color del punto, texto]. El color nunca va solo: el texto dice lo mismo.
const ESTADOS = {
  ok: ["ok", "Todo local, en verde"],
  degradado: ["aviso", "Todo local, degradado"],
  error: ["error", "Todo local, con fallas"],
  sin_conexion: ["error", "Sin conexión con el servicio"],
};
let temporizador = null;
let ultima = 0;
let pintado = null;

function pintar(estado) {
  if (!texto || estado === pintado) return;
  pintado = estado;
  const [color, frase] = ESTADOS[estado] || ESTADOS.error;
  if (punto) punto.dataset.estado = color;
  texto.textContent = frase;
}

async function consultar() {
  ultima = Date.now();
  try {
    const { cuerpo } = await api("/health", { aceptar: [503] });
    pintar(["ok", "degradado", "error"].includes(cuerpo?.estado) ? cuerpo.estado : "error");
  } catch {
    pintar("sin_conexion");
  }
}

function programar() {
  clearTimeout(temporizador);
  temporizador = null;
  if (document.hidden) return;
  const espera = Math.max(0, INTERVALO_MS - (Date.now() - ultima));
  temporizador = setTimeout(async () => { await consultar(); programar(); }, espera);
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) { clearTimeout(temporizador); temporizador = null; return; }
  programar();   // si ya pasaron 60 s desde la última consulta, consulta enseguida
});

// En la barra superior (< 1100 px) la navegación se desplaza en horizontal: la página actual queda a la vista
function centrarActual() {
  const actual = document.querySelector('.navegacion a[aria-current="page"]');
  const lista = actual?.closest("ul");
  if (!lista || lista.scrollWidth <= lista.clientWidth) return;
  const a = actual.getBoundingClientRect();
  const l = lista.getBoundingClientRect();
  lista.scrollLeft += a.left - l.left - (lista.clientWidth - a.width) / 2;
}

// Pista de desplazamiento: el borde de la barra de módulos por el que queda contenido se desvanece (máscara en
// base.css). Sin desplazamiento posible (barra lateral o todo cabe), sin clases.
function marcarDesplazamiento() {
  const lista = document.querySelector(".navegacion ul");
  if (!lista) return;
  const maximo = lista.scrollWidth - lista.clientWidth;
  lista.classList.toggle("mas-izq", maximo > 1 && lista.scrollLeft > 1);
  lista.classList.toggle("mas-der", maximo > 1 && lista.scrollLeft < maximo - 1);
}

centrarActual();
marcarDesplazamiento();
document.querySelector(".navegacion ul")?.addEventListener("scroll", marcarDesplazamiento, { passive: true });
window.addEventListener("resize", marcarDesplazamiento);
if (document.hidden) programar();
else consultar().then(programar);
