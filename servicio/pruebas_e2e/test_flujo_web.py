"""Pruebas de punta a punta de la web con Playwright (Chromium sin interfaz, API síncrona).

Recorren lo que haría el archivista: inicio con el estado del sistema (/health) → cargar una foto → catalogarla →
ver las fuentes de cada campo → calificarla y validarla → buscar → ver las métricas; al final eliminan la foto de
prueba desde la página Archivo (con la confirmación en la página). Además revisan en cada página lo básico de
accesibilidad (aviso de IA, navegación, `alt`, etiquetas, regiones `aria-live`) y que el navegador solo hable con
la web y su `/api` (R8).

Cómo se ejecutan (desde la raíz del repositorio; ver también docker-compose.e2e.yml):

    # Preparación, con internet: construye la imagen de pruebas (Playwright 1.64.0 + pytest)
    docker compose -f docker-compose.yml -f docker-compose.e2e.yml --profile pruebas build e2e
    # Con el sistema levantado (docker compose up -d) y los modelos descargados; no necesita internet:
    docker compose -f docker-compose.yml -f docker-compose.e2e.yml --profile pruebas run --rm e2e

    # Otra foto de prueba (ruta dentro del contenedor; ./data se monta en /datos):
    docker compose -f docker-compose.yml -f docker-compose.e2e.yml --profile pruebas run --rm \
        -e FOTOTECA_E2E_FOTO=/datos/demo/mi_foto.jpg e2e

Usan los modelos reales: catalogar una foto en CPU toma tiempo (la espera máxima se ajusta con
FOTOTECA_E2E_ESPERA_FICHA_S). La foto de prueba nunca puede ser del archivo de referencia ni una ya cargada:
en esos casos la prueba se detiene antes de catalogar, para no tocar datos existentes.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from conftest import ESPERA_FICHA_MS, pedir, subir_foto

PAGINAS = ["index.html", "catalogar.html", "buscar.html", "duplicados.html", "archivo.html", "metricas.html"]
AVISO = "pueden contener errores"
SECCIONES_METRICAS = {"Accesibilidad del archivo", "Latencia por capa", "Caché", "Guardrails", "Uso por modelo",
                      "Enrutador y agente", "Retroalimentación", "Latencia por endpoint"}

# Revisión de accesibilidad que corre dentro de la página
REVISAR_ACCESIBILIDAD = """() => {
  const d = document;
  const controles = [...d.querySelectorAll("input, select, textarea")].filter((c) => c.type !== "hidden");
  return {
    lang: d.documentElement.lang,
    h1: d.querySelectorAll("h1").length,
    saltar: !!d.querySelector("a.saltar[href='#contenido']") && !!d.getElementById("contenido"),
    imagenesSinAlt: [...d.querySelectorAll("img")].filter((i) => !i.hasAttribute("alt")).map((i) => i.src),
    controlesSinEtiqueta: controles.filter((c) => !(c.id && d.querySelector(`label[for="${c.id}"]`))
      && !c.getAttribute("aria-label") && !c.getAttribute("aria-labelledby") && !c.closest("label")).map((c) => c.id || c.name),
    botonesSinNombre: [...d.querySelectorAll("button, a[href]")].filter((b) => !(b.textContent.trim()
      || b.getAttribute("aria-label") || b.querySelector("img[alt]:not([alt=''])"))).length,
    regionesVivas: d.querySelectorAll("[aria-live]").length,
    navegacion: [...d.querySelectorAll("nav.navegacion a")].map((a) => a.getAttribute("href")),
    actual: d.querySelector("nav.navegacion a[aria-current='page']")?.getAttribute("href"),
  };
}"""


def test_inicio_muestra_el_estado_del_sistema(sesion):
    pagina = sesion.pagina
    pagina.goto("/index.html")
    expect(pagina.locator(".aviso-ia")).to_contain_text(AVISO)
    # GET /api/health: estado general y una tarjeta por componente
    expect(pagina.locator("#estado-general .insignia")).to_have_text(re.compile("En verde|Degradado"))
    expect(pagina.locator("#componentes .tarjeta")).to_have_count(5)
    # GET /api/metricas: el archivo en cifras, y los accesos rápidos a las demás páginas
    expect(pagina.locator("#cifras .cifra")).to_have_count(4)
    accesos = pagina.locator("ul.accesos a").evaluate_all("(xs) => xs.map((a) => a.getAttribute('href'))")
    assert accesos == PAGINAS[1:]
    sesion.verificar_r8()


@pytest.mark.parametrize("pagina_web", PAGINAS)
def test_cada_pagina_cumple_lo_basico_de_accesibilidad(sesion, pagina_web):
    pagina = sesion.pagina
    pagina.goto(f"/{pagina_web}")
    pagina.wait_for_load_state("networkidle")
    expect(pagina.locator(".aviso-ia")).to_contain_text(AVISO)
    r = pagina.evaluate(REVISAR_ACCESIBILIDAD)
    assert r["lang"] == "es" and r["h1"] == 1 and r["saltar"], r
    assert r["navegacion"] == PAGINAS and r["actual"] == pagina_web, r
    assert not r["imagenesSinAlt"] and not r["controlesSinEtiqueta"] and not r["botonesSinNombre"], r
    assert r["regionesVivas"] >= 1, r
    # Con el teclado, el primer Tab llega al enlace para saltar al contenido
    pagina.keyboard.press("Tab")
    assert pagina.evaluate("document.activeElement.className") == "saltar"
    expect(pagina.locator(".mensaje.error")).to_have_count(0)
    sesion.verificar_r8()


def test_flujo_cargar_catalogar_validar_buscar_metricas(sesion, foto_de_prueba):
    pagina = sesion.pagina
    # Salvaguarda: la foto no puede ser del archivo de referencia ni una ya cargada (no se tocan datos existentes)
    previo = subir_foto(foto_de_prueba)
    documento = previo["documento_id"]
    if previo.get("ya_existia"):
        pytest.skip(f"La foto de prueba ya estaba en el archivo ({documento}); usa otra con FOTOTECA_E2E_FOTO "
                    "o elimínala desde la página Archivo.")
    eliminado = False
    try:
        # 1. Cargar y catalogar (una sola foto: la llamada es síncrona y muestra la ficha)
        pagina.goto("/catalogar.html")
        pagina.set_input_files("#fotos", str(foto_de_prueba))
        # Vista previa local de la foto elegida, antes de subirla
        expect(pagina.locator("#vista-previa li")).to_have_count(1)
        expect(pagina.locator("#vista-previa")).to_contain_text(foto_de_prueba.name)
        assert pagina.get_attribute("#vista-previa img", "alt")
        pagina.click("#boton-catalogar")
        titulo = pagina.locator("#titulo-revision")
        titulo.wait_for(timeout=ESPERA_FICHA_MS)
        expect(titulo).to_be_focused()
        expect(pagina.locator("#revision figure.foto figcaption")).to_contain_text(documento)
        alt = pagina.input_value("#campo-texto_alternativo")
        assert 0 < len(alt) <= 250, alt
        assert pagina.get_attribute("#revision figure.foto img", "alt")

        # Visor: la foto guardada en grande con su ficha; Esc lo cierra y el foco vuelve a la foto
        boton_foto = pagina.get_by_role("button", name="Ver en grande la foto guardada y su ficha")
        boton_foto.click()
        visor = pagina.locator("dialog#visor")
        expect(visor).to_be_visible()
        expect(visor.locator("#visor-datos")).to_contain_text(documento)
        expect(visor.locator("#visor-medidas")).to_contain_text("sin metadatos EXIF")
        pagina.keyboard.press("Escape")
        expect(visor).to_be_hidden()
        expect(boton_foto).to_be_focused()
        # Si la ficha cita una foto similar, su chip abre el ejemplo en el visor
        chip = pagina.locator("button.chip-foto").first
        if chip.count():
            chip.click()
            expect(visor).to_be_visible()
            expect(pagina.locator("#visor-titulo")).to_have_text("Foto similar usada como ejemplo")
            pagina.get_by_role("button", name="Cerrar").click()
            expect(visor).to_be_hidden()

        # 2. Fuentes: cada campo muestra sus chips o avisa que no tiene fuente verificable
        for campo in ("titular", "texto_alternativo", "descripcion"):
            fuentes = pagina.locator(f"#campo-{campo}-fuentes")
            assert fuentes.locator(".chip").count() + fuentes.locator(".sin-fuente").count() >= 1, campo
        pagina.click("details.pie-tecnico summary")
        tecnico = pagina.locator("details.pie-tecnico")
        expect(tecnico).to_have_attribute("open", "")
        expect(tecnico).to_contain_text("Traza")
        expect(tecnico).to_contain_text("Iteraciones del agente")

        # 3. Opinión y validación: Útil, comentario y «Validar ficha»
        util = pagina.get_by_role("button", name="Útil", exact=True)
        util.click()
        expect(util).to_have_attribute("aria-pressed", "true")
        pagina.fill("#comentario", "Prueba E2E: ficha revisada")
        pagina.get_by_role("button", name="Validar ficha").click()
        expect(pagina.locator("#resultado-opinion .mensaje.ok")).to_contain_text("Ficha validada", timeout=120_000)
        expect(pagina.locator("#revision figure.foto figcaption .insignia")).to_have_text("Validada")
        titular = pagina.input_value("#campo-titular")

        # 4. Buscar por texto (con palabras de la ficha validada): resultados con razones, o un mensaje claro
        pagina.goto("/buscar.html")
        consulta = " ".join(re.findall(r"\w{4,}", titular)[:4]) or "fotografía"
        pagina.fill("#consulta", consulta)
        pagina.click("#formulario-texto button[type=submit]")
        pagina.wait_for_function("() => { const m = document.querySelector('#estado .mensaje');"
                                 " return m && !m.textContent.startsWith('Buscando'); }", timeout=180_000)
        error_busqueda = pagina.locator("#estado .mensaje.error")
        assert error_busqueda.count() == 0, f"La búsqueda «{consulta}» falló: {error_busqueda.first.inner_text()}"
        for tarjeta in pagina.locator("#resultados article").all():
            assert tarjeta.locator("img").get_attribute("alt")
            assert tarjeta.locator(".razones li").count() >= 1
        expect(pagina.locator("#tecnico details.pie-tecnico")).to_have_count(1)

        # 5. Métricas: todas las secciones, gráficas SVG con su tabla y la opinión recién registrada
        pagina.goto("/metricas.html")
        expect(pagina.locator("#estado .mensaje.ok")).to_contain_text("Actualizado")
        secciones = set(pagina.locator("#panel section > h2").all_inner_texts())
        assert SECCIONES_METRICAS <= secciones, SECCIONES_METRICAS - secciones
        assert pagina.locator("#panel svg").count() > 0 and pagina.locator("#panel table").count() > 0
        retro = pagina.locator("#panel section", has=pagina.locator("h2", has_text="Retroalimentación"))
        expect(retro).to_contain_text("fichas validadas")
        _, metricas = pedir("GET", "/metricas")
        assert metricas["retroalimentacion"]["fichas_validadas"] >= 1
        assert metricas["accesibilidad"]["fichas_validadas"] >= 1

        # 6. Limpieza desde Archivo: confirmación en la página (sin window.confirm)
        pagina.goto("/archivo.html")
        fila = pagina.locator(f"#filas tr[data-documento='{documento}']")
        if fila.count():
            fila.get_by_role("button", name=re.compile("^Eliminar")).click()
            confirmacion = pagina.locator("#confirmacion")
            expect(confirmacion).to_be_visible()
            expect(confirmacion.get_by_role("button", name="Cancelar")).to_be_focused()
            confirmacion.get_by_role("button", name="Sí, eliminar").click()
            expect(pagina.locator("#estado")).to_contain_text(f"Eliminado {documento}")
            eliminado = True
        sesion.verificar_r8()
    finally:
        if not eliminado:   # si el flujo se cortó antes, la foto de prueba se elimina por la API
            pedir("DELETE", f"/documentos/{documento}")
