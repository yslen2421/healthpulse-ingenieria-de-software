"""Pruebas unitarias del Protection Proxy (control de acceso por rol)."""
import pytest

from app.dominio.modelos import ItemReceta
from app.servicios.consultas import AccesoDenegado, ConsultaNoEncontrada
from tests.conftest import sintoma


@pytest.fixture
def agendada(sistema, paciente):
    s = sistema.servicio_para(paciente)
    c = s.crear_consulta(paciente.id, sintoma(intensidad=8, horas=24))
    s.realizar_triaje(c.id, "omitir")
    assert c.nombre_estado == "AGENDADA"
    return c


def test_sin_sesion_no_hay_acceso(sistema, paciente):
    with pytest.raises(AccesoDenegado, match="iniciar sesión"):
        sistema.servicio_para(None).crear_consulta(paciente.id, sintoma())


def test_medico_no_puede_crear_consultas(sistema, medico):
    with pytest.raises(AccesoDenegado):
        sistema.servicio_para(medico).crear_consulta(medico.id, sintoma())


def test_paciente_no_crea_consultas_para_otro(sistema, paciente, otro_paciente):
    with pytest.raises(AccesoDenegado):
        sistema.servicio_para(paciente).crear_consulta(otro_paciente.id, sintoma())


def test_otro_paciente_no_ve_la_consulta_ni_la_sala(sistema, agendada, otro_paciente):  # HU-08 CA3
    proxy = sistema.servicio_para(otro_paciente)
    with pytest.raises(AccesoDenegado):
        proxy.obtener(agendada.id)
    with pytest.raises(AccesoDenegado):
        proxy.acceder_sala_webrtc(agendada.id, otro_paciente.id)


def test_paciente_y_medico_asignado_entran_a_la_sala(sistema, agendada, paciente):
    medico = sistema.repo.usuario(agendada.medico_id)
    assert sistema.servicio_para(paciente).acceder_sala_webrtc(agendada.id, paciente.id) == agendada.sala_webrtc_url
    assert sistema.servicio_para(medico).acceder_sala_webrtc(agendada.id, medico.id) == agendada.sala_webrtc_url


def test_no_se_pide_sala_a_nombre_de_otro(sistema, agendada, paciente):
    with pytest.raises(AccesoDenegado):
        sistema.servicio_para(paciente).acceder_sala_webrtc(agendada.id, agendada.medico_id)


def test_medico_no_asignado_no_puede_atender(sistema, agendada, medico, medico2):
    otro = medico2 if agendada.medico_id == medico.id else medico
    proxy = sistema.servicio_para(otro)
    for accion in (lambda: proxy.iniciar_videollamada(agendada.id),
                   lambda: proxy.validar_triaje(agendada.id, 3),
                   lambda: proxy.finalizar_consulta(agendada.id, "Dx", [])):
        with pytest.raises(AccesoDenegado):
            accion()


def test_paciente_no_puede_emitir_receta(sistema, agendada, paciente):
    item = ItemReceta("Ibuprofeno", "400 mg", "c/8h", "3 días")
    with pytest.raises(AccesoDenegado):
        sistema.servicio_para(paciente).finalizar_consulta(agendada.id, "Dx", [item])


def test_solo_admin_reenvia_recetas(sistema, agendada, paciente):
    with pytest.raises(AccesoDenegado):
        sistema.servicio_para(paciente).reenviar_receta(agendada.id)


def test_admin_puede_ver_y_cancelar(sistema, agendada, admin):
    proxy = sistema.servicio_para(admin)
    assert proxy.obtener(agendada.id) is agendada
    proxy.cancelar(agendada.id, "Cancelada por administración")
    assert agendada.nombre_estado == "CANCELADA"


def test_medico_no_puede_cancelar(sistema, agendada):
    medico = sistema.repo.usuario(agendada.medico_id)
    with pytest.raises(AccesoDenegado):
        sistema.servicio_para(medico).cancelar(agendada.id, "x")


def test_usuario_desactivado_pierde_acceso(sistema, paciente):
    paciente.activo = False
    with pytest.raises(AccesoDenegado):
        sistema.servicio_para(paciente).crear_consulta(paciente.id, sintoma())


def test_consulta_inexistente(sistema, admin):
    with pytest.raises(ConsultaNoEncontrada):
        sistema.servicio_para(admin).obtener("CON-NOEXISTE")


def test_paciente_no_hace_el_triaje_de_una_consulta_ajena(sistema, paciente, otro_paciente):
    c = sistema.servicio_para(paciente).crear_consulta(paciente.id, sintoma())
    with pytest.raises(AccesoDenegado):
        sistema.servicio_para(otro_paciente).realizar_triaje(c.id, "omitir")
    assert c.nombre_estado == "EN_TRIAJE"
