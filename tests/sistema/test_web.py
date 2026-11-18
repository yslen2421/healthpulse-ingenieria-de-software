"""Pruebas de sistema: se usa la aplicación web completa como lo haría un usuario (cliente HTTP de Flask)."""
import re

import pytest

from tests.conftest import entrar

TRIAJE_ESTABLE = {"sintoma": "Dolor de garganta", "horas": "30", "intensidad": "5", "descripcion": "",
                  "modo_signos": "sensor", "escenario": "normal"}
TRIAJE_CRITICO = {"sintoma": "Dolor de pecho", "horas": "1", "intensidad": "9", "descripcion": "",
                  "modo_signos": "sensor", "escenario": "hipoxia"}


def crear_consulta(cliente, datos=TRIAJE_ESTABLE):
    r = cliente.post("/paciente/nueva", data=datos)
    assert r.status_code == 302, r.data
    return r.location.rsplit("/", 1)[-1]


def test_salud_para_monitoreo(cliente):
    r = cliente.get("/salud")
    assert r.status_code == 200 and r.json["estado"] == "ok"


def test_pagina_de_inicio_muestra_login(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "Iniciar sesión".encode() in r.data


def test_login_incorrecto(cliente):
    r = entrar(cliente, "paciente@demo.co", "malaclave")
    assert r.location == "/"
    assert "incorrectos".encode() in cliente.get("/").data


@pytest.mark.parametrize("email,panel", [("paciente@demo.co", "/paciente"), ("medico@demo.co", "/medico"),
                                         ("admin@demo.co", "/admin")])
def test_cada_rol_llega_a_su_panel(cliente, email, panel):
    assert entrar(cliente, email).location == panel
    assert cliente.get(panel).status_code == 200
    assert cliente.get("/").location == panel


def test_sin_sesion_redirige_al_login(cliente):
    assert cliente.get("/paciente").location == "/"


def test_paciente_no_entra_al_panel_de_admin(cliente):
    entrar(cliente, "paciente@demo.co")
    assert cliente.get("/admin").status_code == 403


def test_sesion_expira_a_los_15_minutos(app):  # RNF-02
    assert app.permanent_session_lifetime.total_seconds() == 15 * 60


def test_registro_de_paciente(cliente):
    datos = {"nombre": "Nueva Paciente", "documento": "123", "telefono": "300", "email": "nueva@demo.co",
             "password": "clave123", "consentimiento": "si"}
    r = cliente.post("/registro", data=datos)
    assert r.location == "/paciente"
    assert cliente.post("/registro", data=datos).status_code == 400  # correo repetido


def test_registro_sin_consentimiento_se_rechaza(cliente):
    r = cliente.post("/registro", data={"nombre": "X", "documento": "1", "email": "x@demo.co", "password": "clave123"})
    assert r.status_code == 400 and "1581".encode() in r.data
    assert cliente.get("/registro").status_code == 200


def test_triaje_con_datos_invalidos(cliente):
    entrar(cliente, "paciente@demo.co")
    r = cliente.post("/paciente/nueva", data={**TRIAJE_ESTABLE, "intensidad": "15"})
    assert r.status_code == 400 and "intensidad".encode() in r.data.lower()
    assert cliente.get("/paciente/nueva").status_code == 200


def test_cu02_ruta_estable_desde_la_web(cliente):
    entrar(cliente, "paciente@demo.co")
    cid = crear_consulta(cliente)
    html = cliente.get(f"/consulta/{cid}").data.decode()
    assert "AGENDADA" in html and "meet.jit.si" in html
    assert cid in cliente.get("/paciente").data.decode()


def test_cu02_ruta_critica_muestra_alerta_de_urgencias(cliente):
    entrar(cliente, "paciente@demo.co")
    cid = crear_consulta(cliente, TRIAJE_CRITICO)
    html = cliente.get(f"/consulta/{cid}").data.decode()
    assert "REMITIDA URGENCIAS" in html and "línea 123" in html and "meet.jit.si" not in html


def test_otro_paciente_no_puede_ver_la_consulta(cliente):
    entrar(cliente, "paciente@demo.co")
    cid = crear_consulta(cliente)
    cliente.get("/logout")
    entrar(cliente, "paciente2@demo.co")
    assert cliente.get(f"/consulta/{cid}").status_code == 403


def test_consulta_inexistente(cliente):
    entrar(cliente, "admin@demo.co")
    assert cliente.get("/consulta/CON-NOEXISTE").status_code == 404


def test_flujo_completo_medico_con_receta(cliente, app):
    entrar(cliente, "paciente@demo.co")
    cid = crear_consulta(cliente)
    medico = app.sistema.repo.usuario(app.sistema.repo.consulta(cid).medico_id)
    cliente.get("/logout")
    entrar(cliente, medico.email)
    assert cid in cliente.get("/medico").data.decode()
    cliente.post(f"/consulta/{cid}/validar", data={"nivel": "4"})
    cliente.post(f"/consulta/{cid}/iniciar")
    receta = {"diagnostico": "Faringitis viral", "medicamento1": "Acetaminofén", "dosis1": "500 mg",
              "frecuencia1": "cada 8 horas", "duracion1": "3 días"}
    cliente.post(f"/consulta/{cid}/finalizar", data=receta)
    html = cliente.get(f"/consulta/{cid}").data.decode()
    assert "CERRADA" in html and "CONFIRMADA" in html and re.search(r"Pedido PED-\d{6}", html)


def test_accion_invalida_muestra_error_y_no_rompe(cliente, app):
    entrar(cliente, "paciente@demo.co")
    cid = crear_consulta(cliente)
    medico = app.sistema.repo.usuario(app.sistema.repo.consulta(cid).medico_id)
    cliente.get("/logout")
    entrar(cliente, medico.email)
    r = cliente.post(f"/consulta/{cid}/finalizar", data={"diagnostico": "x"})  # aún no está EN_CURSO
    assert r.status_code == 302
    assert "No se puede finalizar".encode() in cliente.get(f"/consulta/{cid}").data


def test_lista_de_espera_y_medico_disponible(cliente, app):
    for m in app.sistema.repo.medicos():
        m.cambiar_disponibilidad("DESCONECTADO")
    entrar(cliente, "paciente@demo.co")
    cid = crear_consulta(cliente)
    assert "Posición" in cliente.get(f"/consulta/{cid}").data.decode()
    cliente.get("/logout")
    entrar(cliente, "medico@demo.co")
    r = cliente.post("/medico/disponibilidad", data={"estado": "DISPONIBLE"}, follow_redirects=True)
    assert "Se asignaron 1 paciente".encode() in r.data


def test_paciente_cancela_su_consulta(cliente):
    entrar(cliente, "paciente@demo.co")
    cid = crear_consulta(cliente)
    cliente.post(f"/consulta/{cid}/cancelar")
    assert "CANCELADA" in cliente.get(f"/consulta/{cid}").data.decode()


def test_admin_simuladores_y_reenvio(cliente, app):
    entrar(cliente, "admin@demo.co")
    cliente.post("/admin/simulador", data={"accion": "farmacia_toggle"})
    assert app.sistema.farmacia_legacy.caida
    cliente.post("/admin/simulador", data={"accion": "ia_toggle"})
    assert not app.sistema.motor_ia.disponible
    assert cliente.post("/admin/simulador", data={"accion": "nada"}).status_code == 400
    cliente.get("/logout")
    # una consulta termina con la farmacia caída
    entrar(cliente, "paciente@demo.co")
    cid = crear_consulta(cliente)
    medico = app.sistema.repo.usuario(app.sistema.repo.consulta(cid).medico_id)
    cliente.get("/logout")
    entrar(cliente, medico.email)
    cliente.post(f"/consulta/{cid}/iniciar")
    cliente.post(f"/consulta/{cid}/finalizar", data={"diagnostico": "Dx", "medicamento1": "Ibuprofeno",
                                                     "dosis1": "400 mg", "frecuencia1": "c/8h", "duracion1": "3 días"})
    cliente.get("/logout")
    entrar(cliente, "admin@demo.co")
    assert "Reenviar" in cliente.get("/admin").data.decode()
    r = cliente.post(f"/admin/reenviar/{cid}", follow_redirects=True)
    assert "sigue sin responder".encode() in r.data
    cliente.post("/admin/simulador", data={"accion": "farmacia_toggle"})
    r = cliente.post(f"/admin/reenviar/{cid}", follow_redirects=True)
    assert "confirmó".encode() in r.data
    r = cliente.post(f"/admin/reenviar/{cid}", follow_redirects=True)
    assert "No hay una receta pendiente".encode() in r.data


def test_admin_alerta_de_espera_larga_con_reloj(cliente, app):
    for m in app.sistema.repo.medicos():
        m.cambiar_disponibilidad("DESCONECTADO")
    entrar(cliente, "paciente@demo.co")
    crear_consulta(cliente, {**TRIAJE_ESTABLE, "intensidad": "8"})
    cliente.get("/logout")
    entrar(cliente, "admin@demo.co")
    cliente.post("/admin/simulador", data={"accion": "reloj_31"})
    html = cliente.get("/admin").data.decode()
    assert "Alertas de espera larga" in html
    cliente.post("/admin/simulador", data={"accion": "reloj_16"})
    cliente.post("/admin/simulador", data={"accion": "reloj_reset"})


def test_admin_activa_y_desactiva_medicos(cliente, app):
    entrar(cliente, "admin@demo.co")
    medico = app.sistema.repo.buscar_por_email("medico@demo.co")
    cliente.post(f"/admin/medico/{medico.id}/activo")
    assert not medico.activo
    cliente.post(f"/admin/medico/{medico.id}/activo")
    assert medico.activo
    assert cliente.post("/admin/medico/NOEXISTE/activo").status_code == 404


def test_demo_alerta_hu14_desde_el_admin(cliente, app):
    """Guion de la demo: el admin desactiva médicos, adelanta el reloj y al reactivar se asigna el paciente."""
    entrar(cliente, "admin@demo.co")
    medicos = app.sistema.repo.medicos()
    for m in medicos:
        cliente.post(f"/admin/medico/{m.id}/activo")
    cliente.get("/logout")
    entrar(cliente, "paciente@demo.co")
    cid = crear_consulta(cliente, {**TRIAJE_ESTABLE, "intensidad": "8"})
    assert app.sistema.repo.consulta(cid).nombre_estado == "EN_ESPERA"
    cliente.get("/logout")
    entrar(cliente, "admin@demo.co")
    cliente.post("/admin/simulador", data={"accion": "reloj_31"})
    assert "Alertas de espera larga" in cliente.get("/admin").data.decode()
    r = cliente.post(f"/admin/medico/{medicos[0].id}/activo", follow_redirects=True)
    assert "lista de espera: 1".encode() in r.data
    assert app.sistema.repo.consulta(cid).nombre_estado == "AGENDADA"
    assert "Alertas de espera larga" not in cliente.get("/admin").data.decode()
