"""Pruebas unitarias del patrón State: cada transición de la máquina de estados (Figura 8)."""
from datetime import timedelta

import pytest

from app.dominio.estados import TransicionInvalida
from app.dominio.modelos import ConsultaMedica, DatoInvalido
from tests.conftest import AHORA, sintoma

T = AHORA + timedelta(minutes=1)


def llevar_a(consulta, estado):
    """Lleva una consulta nueva hasta el estado pedido usando solo transiciones válidas."""
    pasos = {
        "EN_TRIAJE": [],
        "EN_ESPERA": [lambda c: c.poner_en_espera(T)],
        "REMITIDA_URGENCIAS": [lambda c: c.remitir_urgencias(T)],
        "AGENDADA": [lambda c: c.agendar("MED-1", T, "https://sala", T)],
        "EN_CURSO": [lambda c: c.agendar("MED-1", T, "https://sala", T), lambda c: c.iniciar_videollamada(T)],
        "FINALIZADA": [lambda c: c.agendar("MED-1", T, "https://sala", T), lambda c: c.iniciar_videollamada(T),
                       lambda c: c.finalizar("Dx", T)],
        "CERRADA": [lambda c: c.agendar("MED-1", T, "https://sala", T), lambda c: c.iniciar_videollamada(T),
                    lambda c: c.finalizar("Dx", T), lambda c: c.cerrar(T)],
        "CANCELADA": [lambda c: c.cancelar("motivo", T)],
    }
    for paso in pasos[estado]:
        paso(consulta)
    assert consulta.nombre_estado == estado
    return consulta


ACCIONES = {
    "agendar": lambda c: c.agendar("MED-2", T, "https://otra", T),
    "poner_en_espera": lambda c: c.poner_en_espera(T),
    "remitir_urgencias": lambda c: c.remitir_urgencias(T),
    "iniciar_videollamada": lambda c: c.iniciar_videollamada(T),
    "finalizar": lambda c: c.finalizar("Dx", T),
    "cerrar": lambda c: c.cerrar(T),
    "cancelar": lambda c: c.cancelar("motivo", T),
}

# Tabla de transiciones válidas: (estado origen, acción) -> estado destino
VALIDAS = {
    ("EN_TRIAJE", "agendar"): "AGENDADA",
    ("EN_TRIAJE", "poner_en_espera"): "EN_ESPERA",
    ("EN_TRIAJE", "remitir_urgencias"): "REMITIDA_URGENCIAS",
    ("EN_TRIAJE", "cancelar"): "CANCELADA",
    ("EN_ESPERA", "agendar"): "AGENDADA",
    ("EN_ESPERA", "cancelar"): "CANCELADA",
    ("AGENDADA", "iniciar_videollamada"): "EN_CURSO",
    ("AGENDADA", "cancelar"): "CANCELADA",
    ("EN_CURSO", "finalizar"): "FINALIZADA",
    ("FINALIZADA", "cerrar"): "CERRADA",
}
ESTADOS = ["EN_TRIAJE", "EN_ESPERA", "REMITIDA_URGENCIAS", "AGENDADA", "EN_CURSO", "FINALIZADA", "CERRADA", "CANCELADA"]
TODAS = [(e, a) for e in ESTADOS for a in ACCIONES]


@pytest.mark.parametrize("origen,accion", [k for k in TODAS if k in VALIDAS])
def test_transiciones_validas(origen, accion):
    c = llevar_a(ConsultaMedica("PAC-1", [sintoma()], AHORA), origen)
    ACCIONES[accion](c)
    assert c.nombre_estado == VALIDAS[(origen, accion)]


@pytest.mark.parametrize("origen,accion", [k for k in TODAS if k not in VALIDAS])
def test_transiciones_invalidas_se_rechazan(origen, accion):
    c = llevar_a(ConsultaMedica("PAC-1", [sintoma()], AHORA), origen)
    with pytest.raises(TransicionInvalida):
        ACCIONES[accion](c)
    assert c.nombre_estado == origen  # el estado no cambia


def test_consulta_nueva_empieza_en_triaje_y_registra_bitacora(consulta):
    assert consulta.nombre_estado == "EN_TRIAJE"
    assert "EN_TRIAJE" in consulta.bitacora[0][1]


def test_consulta_sin_sintomas_no_se_crea():
    with pytest.raises(DatoInvalido):
        ConsultaMedica("PAC-1", [], AHORA)


def test_agendar_guarda_medico_fecha_y_sala(consulta):
    consulta.agendar("MED-9", T, "https://sala/9", T)
    assert (consulta.medico_id, consulta.fecha_hora_cita, consulta.sala_webrtc_url) == ("MED-9", T, "https://sala/9")


def test_espera_guarda_desde_cuando(consulta):
    consulta.poner_en_espera(T)
    assert consulta.en_espera_desde == T


def test_cancelar_guarda_motivo(consulta):
    consulta.cancelar("", T)
    assert consulta.motivo_cancelacion == "Sin motivo"


def test_cada_cambio_de_estado_queda_en_bitacora(consulta):
    llevar_a(consulta, "CERRADA")
    cambios = [t for _, t in consulta.bitacora if t.startswith("Cambio de estado")]
    assert len(cambios) == 4
    assert cambios[-1] == "Cambio de estado: FINALIZADA -> CERRADA"


def test_estados_finales():
    for estado in ("REMITIDA_URGENCIAS", "CERRADA", "CANCELADA"):
        c = llevar_a(ConsultaMedica("P", [sintoma()], AHORA), estado)
        assert c.estado.es_final
