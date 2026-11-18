"""Patrón State: un estado por cada estado de la máquina de estados (Figura 8).

Cada clase solo implementa las transiciones que la máquina permite. Si se pide
una transición que no existe (por ejemplo, cancelar una consulta CERRADA), la
clase base lanza TransicionInvalida.
"""
from __future__ import annotations

from abc import ABC
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .modelos import ConsultaMedica


class TransicionInvalida(Exception):
    """La transición pedida no existe en la máquina de estados."""


class EstadoConsultaState(ABC):
    nombre = "ABSTRACTO"
    es_final = False

    def _no_permitido(self, accion: str):
        raise TransicionInvalida(f"No se puede {accion} una consulta en estado {self.nombre}.")

    def agendar(self, ctx: "ConsultaMedica", medico_id: str, fecha: datetime, sala_url: str, ahora: datetime):
        self._no_permitido("agendar")

    def poner_en_espera(self, ctx: "ConsultaMedica", ahora: datetime):
        self._no_permitido("poner en espera")

    def remitir_urgencias(self, ctx: "ConsultaMedica", ahora: datetime):
        self._no_permitido("remitir a urgencias")

    def iniciar_videollamada(self, ctx: "ConsultaMedica", ahora: datetime):
        self._no_permitido("iniciar la videollamada de")

    def finalizar(self, ctx: "ConsultaMedica", diagnostico: str, ahora: datetime):
        self._no_permitido("finalizar")

    def cerrar(self, ctx: "ConsultaMedica", ahora: datetime):
        self._no_permitido("cerrar")

    def cancelar(self, ctx: "ConsultaMedica", motivo: str, ahora: datetime):
        self._no_permitido("cancelar")

    def __repr__(self) -> str:  # pragma: no cover
        return self.nombre


def _asignar_cita(ctx, medico_id, fecha, sala_url, ahora):
    ctx.medico_id = medico_id
    ctx.fecha_hora_cita = fecha
    ctx.sala_webrtc_url = sala_url
    ctx.set_estado(EstadoAgendada(), ahora)


def _cancelar(ctx, motivo, ahora):
    ctx.motivo_cancelacion = motivo or "Sin motivo"
    ctx.set_estado(EstadoCancelada(), ahora)


class EstadoEnTriaje(EstadoConsultaState):
    nombre = "EN_TRIAJE"

    def agendar(self, ctx, medico_id, fecha, sala_url, ahora):
        _asignar_cita(ctx, medico_id, fecha, sala_url, ahora)

    def poner_en_espera(self, ctx, ahora):
        ctx.en_espera_desde = ahora
        ctx.set_estado(EstadoEnEspera(), ahora)

    def remitir_urgencias(self, ctx, ahora):
        ctx.set_estado(EstadoRemitidaUrgencias(), ahora)

    def cancelar(self, ctx, motivo, ahora):
        _cancelar(ctx, motivo, ahora)


class EstadoEnEspera(EstadoConsultaState):
    nombre = "EN_ESPERA"

    def agendar(self, ctx, medico_id, fecha, sala_url, ahora):
        _asignar_cita(ctx, medico_id, fecha, sala_url, ahora)

    def cancelar(self, ctx, motivo, ahora):
        _cancelar(ctx, motivo, ahora)


class EstadoAgendada(EstadoConsultaState):
    nombre = "AGENDADA"

    def iniciar_videollamada(self, ctx, ahora):
        ctx.fecha_inicio_video = ahora
        ctx.set_estado(EstadoEnCurso(), ahora)

    def cancelar(self, ctx, motivo, ahora):
        _cancelar(ctx, motivo, ahora)


class EstadoEnCurso(EstadoConsultaState):
    nombre = "EN_CURSO"

    def finalizar(self, ctx, diagnostico, ahora):
        ctx.diagnostico = diagnostico
        ctx.set_estado(EstadoFinalizada(), ahora)


class EstadoFinalizada(EstadoConsultaState):
    nombre = "FINALIZADA"

    def cerrar(self, ctx, ahora):
        ctx.set_estado(EstadoCerrada(), ahora)


class EstadoRemitidaUrgencias(EstadoConsultaState):
    nombre = "REMITIDA_URGENCIAS"
    es_final = True


class EstadoCerrada(EstadoConsultaState):
    nombre = "CERRADA"
    es_final = True


class EstadoCancelada(EstadoConsultaState):
    nombre = "CANCELADA"
    es_final = True
