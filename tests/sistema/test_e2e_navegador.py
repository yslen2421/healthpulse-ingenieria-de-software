"""Prueba de extremo a extremo (E2E) en un navegador real con Playwright.

Recorre la demo completa del CU-02 y guarda capturas en docs/capturas.
Solo corre si se indica la URL del servidor, por ejemplo:
    E2E_URL=http://127.0.0.1:8000 pytest tests/sistema/test_e2e_navegador.py
    E2E_URL=https://healthpulse-grupo3.onrender.com pytest tests/sistema/test_e2e_navegador.py
"""
import os
from pathlib import Path

import pytest

URL = os.environ.get("E2E_URL")
CAPTURAS = Path(__file__).resolve().parents[2] / "docs" / "capturas"
pytestmark = pytest.mark.skipif(not URL, reason="Defina E2E_URL para correr la prueba en el navegador")


@pytest.fixture(scope="module")
def navegador():
    from playwright.sync_api import sync_playwright
    CAPTURAS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        nav = p.chromium.launch()
        yield nav
        nav.close()


def pagina_nueva(navegador):
    contexto = navegador.new_context(viewport={"width": 1280, "height": 860}, device_scale_factor=1)
    return contexto.new_page()


def foto(page, nombre):
    page.screenshot(path=str(CAPTURAS / f"{nombre}.png"), full_page=True)


def entrar(page, email):
    page.goto(URL + "/logout")
    page.fill("#email", email)
    page.fill("#password", "demo123")
    page.click("button[type=submit]")


def test_e2e_demo_completa(navegador):
    page = pagina_nueva(navegador)
    page.goto(URL)
    foto(page, "01_inicio")

    # 1. Paciente: triaje estable con sensor simulado
    entrar(page, "paciente@demo.co")
    page.click("text=Nueva consulta")
    page.fill("#sintoma", "Fiebre y dolor de garganta")
    page.fill("#horas", "20")
    page.fill("#intensidad", "6")
    page.fill("#descripcion", "Me duele al tragar desde ayer")
    page.select_option("#escenario", "fiebre")
    foto(page, "02_formulario_triaje")
    page.click("text=Enviar y clasificar")
    page.wait_for_selector("text=Resultado del triaje")
    assert page.is_visible("text=AGENDADA")
    assert page.is_visible("text=Entrar a la sala de video (WebRTC)")
    foto(page, "03_resultado_agendada")
    consulta_url = page.url

    # 2. Paciente: caso crítico con SpO2 baja
    page.goto(URL + "/paciente/nueva")
    page.fill("#sintoma", "Dificultad para respirar")
    page.fill("#horas", "2")
    page.fill("#intensidad", "9")
    page.select_option("#escenario", "hipoxia")
    page.click("text=Enviar y clasificar")
    page.wait_for_selector(".urgencia")
    foto(page, "04_remitida_urgencias")

    # 3. Médico: ve su cola, inicia y finaliza con receta
    medico_email = "medico@demo.co"
    entrar(page, medico_email)
    if not page.is_visible("text=Atender"):
        entrar(page, "medico2@demo.co")
    foto(page, "05_cola_medico")
    page.goto(consulta_url)
    page.click("text=Iniciar videoconsulta")
    page.wait_for_selector("text=Finalizar consulta y emitir receta")
    page.fill("#diagnostico", "Faringitis viral")
    page.fill("input[name=medicamento1]", "Acetaminofén")
    page.fill("input[name=dosis1]", "500 mg")
    page.fill("input[name=frecuencia1]", "cada 8 horas")
    page.fill("input[name=duracion1]", "3 días")
    foto(page, "06_videoconsulta_receta")
    page.click("text=Finalizar y enviar receta a la farmacia")
    page.wait_for_selector("text=Receta digital")
    assert page.is_visible("text=CERRADA")
    foto(page, "07_receta_cerrada")

    # 4. Administrador: estadísticas, simuladores y alertas
    entrar(page, "admin@demo.co")
    page.wait_for_selector("text=Panel del administrador")
    foto(page, "08_panel_admin")

    # 5. Protection Proxy: otro paciente intenta ver la consulta
    entrar(page, "paciente2@demo.co")
    page.goto(consulta_url)
    assert page.is_visible("text=Acceso denegado")
    foto(page, "09_acceso_denegado")


def test_e2e_vista_celular(navegador):
    """La página debe verse bien en un celular (RNF-04 usabilidad)."""
    from playwright.sync_api import sync_playwright  # noqa: F401
    contexto = navegador.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1)
    page = contexto.new_page()
    page.goto(URL + "/logout")
    page.fill("#email", "paciente@demo.co")
    page.fill("#password", "demo123")
    page.click("button[type=submit]")
    page.goto(URL + "/paciente/nueva")
    ancho = page.evaluate("document.documentElement.scrollWidth")
    assert ancho <= 390, f"La página se desborda horizontalmente ({ancho}px)"
    foto(page, "10_celular")
