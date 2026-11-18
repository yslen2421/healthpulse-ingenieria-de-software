"""Pruebas unitarias del agendamiento, la lista de espera y los temporizadores."""
from datetime import timedelta

from app.dominio.enums import EstadoMedicoEnum, NivelTriajeEnum
from app.dominio.modelos import ConsultaMedica, TriajeIA
from tests.conftest import sintoma


def consulta_con_nivel(sistema, paciente_id, nivel):
    c = ConsultaMedica(paciente_id, [sintoma()], sistema.reloj.ahora())
    c.triaje = TriajeIA(NivelTriajeEnum(nivel), "prueba")
    return sistema.repo.guardar_consulta(c)


def desconectar_todos(sistema):
    for m in sistema.repo.medicos():
        m.cambiar_disponibilidad(EstadoMedicoEnum.DESCONECTADO)


def test_asigna_al_medico_con_menos_carga(sistema, paciente, medico, medico2):
    ag = sistema.agendamiento
    c1 = consulta_con_nivel(sistema, paciente.id, 3)
    ag.asignar(c1)
    c2 = consulta_con_nivel(sistema, paciente.id, 4)
    ag.asignar(c2)
    assert {c1.medico_id, c2.medico_id} == {medico.id, medico2.id}


def test_hora_de_cita_segun_nivel(sistema, paciente):
    ag = sistema.agendamiento
    for nivel, minutos in ((3, 0), (4, 30), (5, 120)):
        c = consulta_con_nivel(sistema, paciente.id, nivel)
        ag.asignar(c)
        diferencia = (c.fecha_hora_cita - c.fecha_hora_creacion).total_seconds() / 60
        assert abs(diferencia - minutos) < 1
        assert diferencia <= NivelTriajeEnum(nivel).minutos_maximos_cita or nivel == 3


def test_sin_medicos_va_a_lista_de_espera(sistema, paciente):
    desconectar_todos(sistema)
    c = consulta_con_nivel(sistema, paciente.id, 3)
    assert not sistema.agendamiento.asignar(c)
    assert c.nombre_estado == "EN_ESPERA"
    assert "lista de espera" in sistema.repo.notificaciones[paciente.id][0]["mensaje"]


def test_medico_desactivado_no_recibe_citas(sistema, medico, medico2):
    medico.activo = False
    medico2.activo = False
    assert sistema.agendamiento.medico_candidato() is None


def test_lista_de_espera_ordenada_por_nivel_y_llegada(sistema, paciente, otro_paciente):
    desconectar_todos(sistema)
    ag = sistema.agendamiento
    v = consulta_con_nivel(sistema, paciente.id, 5)
    ag.asignar(v)
    sistema.reloj.adelantar(1)
    iii_a = consulta_con_nivel(sistema, otro_paciente.id, 3)
    ag.asignar(iii_a)
    sistema.reloj.adelantar(1)
    iii_b = consulta_con_nivel(sistema, paciente.id, 3)
    ag.asignar(iii_b)
    assert [c.id for c in ag.lista_espera()] == [iii_a.id, iii_b.id, v.id]
    assert ag.posicion_en_espera(v) == 3


def test_medico_disponible_procesa_la_lista(sistema, paciente, medico):
    desconectar_todos(sistema)
    ag = sistema.agendamiento
    c = consulta_con_nivel(sistema, paciente.id, 4)
    ag.asignar(c)
    medico.cambiar_disponibilidad(EstadoMedicoEnum.DISPONIBLE)
    assert ag.procesar_lista_espera() == 1
    assert c.nombre_estado == "AGENDADA" and c.medico_id == medico.id
    assert ag.posicion_en_espera(c) == 0


def test_cola_del_medico_por_nivel(sistema, paciente, medico, medico2):
    medico2.cambiar_disponibilidad(EstadoMedicoEnum.DESCONECTADO)
    ag = sistema.agendamiento
    c5 = consulta_con_nivel(sistema, paciente.id, 5)
    ag.asignar(c5)
    c3 = consulta_con_nivel(sistema, paciente.id, 3)
    ag.asignar(c3)
    assert [c.id for c in ag.cola_de_medico(medico.id)] == [c3.id, c5.id]


def test_alerta_espera_larga_nivel_III(sistema, paciente, admin):  # HU-14
    desconectar_todos(sistema)
    ag = sistema.agendamiento
    c = consulta_con_nivel(sistema, paciente.id, 3)
    ag.asignar(c)
    assert ag.revisar_alertas_espera() == []
    sistema.reloj.adelantar(31)
    alertas = ag.revisar_alertas_espera()
    assert len(alertas) == 1 and alertas[0]["minutos"] == 31
    assert len(ag.revisar_alertas_espera()) == 1  # no se duplica
    assert "nivel III" in sistema.repo.notificaciones[admin.id][0]["mensaje"]


def test_alerta_se_cierra_cuando_el_paciente_es_atendido(sistema, paciente, medico):  # HU-14 CA2
    desconectar_todos(sistema)
    ag = sistema.agendamiento
    c = consulta_con_nivel(sistema, paciente.id, 3)
    ag.asignar(c)
    sistema.reloj.adelantar(31)
    ag.revisar_alertas_espera()
    medico.cambiar_disponibilidad(EstadoMedicoEnum.DISPONIBLE)
    ag.procesar_lista_espera()
    assert ag.revisar_alertas_espera() == []
    assert sistema.repo.alertas_admin[0]["cerrada"] is not None


def test_nivel_IV_no_genera_alerta(sistema, paciente):
    desconectar_todos(sistema)
    c = consulta_con_nivel(sistema, paciente.id, 4)
    sistema.agendamiento.asignar(c)
    sistema.reloj.adelantar(45)
    assert sistema.agendamiento.revisar_alertas_espera() == []


def test_inasistencia_despues_de_15_minutos(sistema, paciente):
    c = consulta_con_nivel(sistema, paciente.id, 3)
    sistema.agendamiento.asignar(c)
    sistema.reloj.adelantar(10)
    assert sistema.agendamiento.revisar_inasistencias() == 0
    sistema.reloj.adelantar(6)
    assert sistema.agendamiento.revisar_inasistencias() == 1
    assert c.nombre_estado == "CANCELADA" and "Inasistencia" in c.motivo_cancelacion


def test_reloj_se_reinicia(sistema):
    antes = sistema.reloj.ahora()
    sistema.reloj.adelantar(60)
    assert sistema.reloj.ahora() - antes >= timedelta(minutes=60)
    sistema.reloj.reiniciar()
    assert sistema.reloj.ahora() - antes < timedelta(minutes=1)


def test_lista_de_espera_se_detiene_cuando_no_quedan_medicos(sistema, paciente, otro_paciente, medico):
    """Si se acaban los médicos a mitad de la lista, se para y el resto sigue esperando en orden."""
    desconectar_todos(sistema)
    ag = sistema.agendamiento
    c1 = consulta_con_nivel(sistema, paciente.id, 3)
    ag.asignar(c1)
    c2 = consulta_con_nivel(sistema, otro_paciente.id, 4)
    ag.asignar(c2)
    medico.cambiar_disponibilidad(EstadoMedicoEnum.DISPONIBLE)
    candidato_real, llamadas = ag.medico_candidato, []

    def solo_un_medico():  # el médico queda libre para un solo paciente
        llamadas.append(1)
        return candidato_real() if len(llamadas) == 1 else None
    ag.medico_candidato = solo_un_medico
    assert ag.procesar_lista_espera() == 1
    assert c1.nombre_estado == "AGENDADA" and c2.nombre_estado == "EN_ESPERA"
