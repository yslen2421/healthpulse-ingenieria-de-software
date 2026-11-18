"""Pruebas de integración: los servicios trabajando juntos en el flujo completo del CU-02 y siguientes."""
import pytest

from app.dominio.enums import EstadoEnvioRecetaEnum, EstadoMedicoEnum
from app.dominio.modelos import DatoInvalido, ItemReceta
from tests.conftest import sintoma

RECETA = [ItemReceta("Acetaminofén", "500 mg", "cada 8 horas", "3 días")]


def triaje(sistema, paciente, s, modo="omitir", escenario="normal", manual=None):
    proxy = sistema.servicio_para(paciente)
    c = proxy.crear_consulta(paciente.id, s)
    return proxy.realizar_triaje(c.id, modo, escenario, manual)


def test_ruta_estable_agenda_con_sala_y_notifica(sistema, paciente):
    c = triaje(sistema, paciente, sintoma("Fiebre", 24, 7), "sensor", "fiebre")
    assert c.nombre_estado == "AGENDADA"
    assert c.signos_vitales and c.sala_webrtc_url.startswith("https://meet.jit.si/")
    assert "Cita confirmada" in sistema.repo.notificaciones[paciente.id][0]["mensaje"]
    assert "Nueva cita" in sistema.repo.notificaciones[c.medico_id][0]["mensaje"]
    textos = [t for _, t in c.bitacora]
    assert any("Lectura del sensor" in t for t in textos) and any("Triaje nivel" in t for t in textos)


def test_ruta_critica_remite_a_urgencias_y_avisa_al_admin(sistema, paciente, admin):
    c = triaje(sistema, paciente, sintoma("Dolor de pecho", 1, 9), "sensor", "hipoxia")
    assert c.nombre_estado == "REMITIDA_URGENCIAS"
    assert c.medico_id is None and c.sala_webrtc_url is None  # no hay videollamada
    assert "123" in sistema.repo.notificaciones[paciente.id][0]["mensaje"]
    assert "remitida a urgencias" in sistema.repo.notificaciones[admin.id][0]["mensaje"]
    assert "remisión" in c.bitacora[-1][1]


def test_sensor_falla_y_se_usan_signos_manuales(sistema, paciente):
    c = triaje(sistema, paciente, sintoma(intensidad=5), "sensor", "falla", {"fc": 88, "spo2": 97, "temp": 37})
    assert c.signos_vitales.origen.value == "manual"
    assert any("no respondió en 5 s" in t for _, t in c.bitacora)


def test_ia_caida_no_bloquea_el_triaje(sistema, paciente):
    sistema.motor_ia.disponible = False
    c = triaje(sistema, paciente, sintoma(intensidad=6))
    assert c.triaje.origen == "Reglas de respaldo"
    assert c.nombre_estado == "AGENDADA"


def test_triaje_no_se_repite(sistema, paciente):
    c = triaje(sistema, paciente, sintoma())
    with pytest.raises(DatoInvalido):
        sistema.servicio_para(paciente).realizar_triaje(c.id, "omitir")


def test_flujo_completo_hasta_cerrada_con_receta(sistema, paciente):
    c = triaje(sistema, paciente, sintoma("Tos", 48, 5))
    medico = sistema.repo.usuario(c.medico_id)
    proxy = sistema.servicio_para(medico)
    proxy.validar_triaje(c.id, 4)
    proxy.iniciar_videollamada(c.id)
    assert c.nombre_estado == "EN_CURSO" and medico.disponibilidad == EstadoMedicoEnum.OCUPADO
    proxy.finalizar_consulta(c.id, "Infección respiratoria leve", RECETA)
    assert c.nombre_estado == "CERRADA"
    assert c.receta.estado_envio == EstadoEnvioRecetaEnum.CONFIRMADA
    assert medico.disponibilidad == EstadoMedicoEnum.DISPONIBLE
    assert any("Farmacia confirmó" in t for _, t in c.bitacora)


def test_consulta_sin_receta_tambien_se_cierra(sistema, paciente):
    c = triaje(sistema, paciente, sintoma())
    proxy = sistema.servicio_para(sistema.repo.usuario(c.medico_id))
    proxy.iniciar_videollamada(c.id)
    proxy.finalizar_consulta(c.id, "Control sin medicamentos", [])
    assert c.nombre_estado == "CERRADA" and c.receta is None


def test_farmacia_caida_deja_pendiente_y_admin_reenvia(sistema, paciente, admin):  # HU-10, RNF-06
    sistema.farmacia_legacy.caida = True
    c = triaje(sistema, paciente, sintoma())
    proxy_med = sistema.servicio_para(sistema.repo.usuario(c.medico_id))
    proxy_med.iniciar_videollamada(c.id)
    proxy_med.finalizar_consulta(c.id, "Dx", RECETA)
    assert c.nombre_estado == "FINALIZADA"
    assert c.receta.estado_envio == EstadoEnvioRecetaEnum.PENDIENTE and c.receta.intentos_envio == 3
    assert "pendiente" in sistema.repo.notificaciones[admin.id][0]["mensaje"]
    proxy_admin = sistema.servicio_para(admin)
    assert not proxy_admin.reenviar_receta(c.id)          # sigue caída
    sistema.farmacia_legacy.caida = False
    assert proxy_admin.reenviar_receta(c.id)               # se recupera
    assert c.nombre_estado == "CERRADA" and c.receta.intentos_envio == 7
    with pytest.raises(DatoInvalido):
        proxy_admin.reenviar_receta(c.id)                  # ya no está pendiente


def test_al_finalizar_el_medico_toma_al_siguiente_de_la_lista(sistema, paciente, otro_paciente, medico, medico2):
    medico2.cambiar_disponibilidad(EstadoMedicoEnum.DESCONECTADO)
    c1 = triaje(sistema, paciente, sintoma(intensidad=7))
    proxy = sistema.servicio_para(medico)
    proxy.iniciar_videollamada(c1.id)                      # médico ocupado
    c2 = triaje(sistema, otro_paciente, sintoma(intensidad=5))
    assert c2.nombre_estado == "EN_ESPERA"
    proxy.finalizar_consulta(c1.id, "Dx", [])
    assert c2.nombre_estado == "AGENDADA" and c2.medico_id == medico.id


def test_sala_cerrada_despues_de_la_consulta(sistema, paciente):
    c = triaje(sistema, paciente, sintoma())
    proxy_med = sistema.servicio_para(sistema.repo.usuario(c.medico_id))
    proxy_med.iniciar_videollamada(c.id)
    proxy_med.finalizar_consulta(c.id, "Dx", [])
    with pytest.raises(DatoInvalido):
        sistema.servicio_para(paciente).acceder_sala_webrtc(c.id, paciente.id)


def test_validar_triaje_solo_en_consultas_activas(sistema, paciente):
    c = triaje(sistema, paciente, sintoma())
    proxy_med = sistema.servicio_para(sistema.repo.usuario(c.medico_id))
    sistema.servicio_para(paciente).cancelar(c.id, "Ya me siento mejor")
    with pytest.raises(DatoInvalido):
        proxy_med.validar_triaje(c.id, 3)
