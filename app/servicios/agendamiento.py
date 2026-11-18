"""Lógica de agendamiento (lo que en la secuencia hace ControllerAgendamiento)."""
from __future__ import annotations

from datetime import timedelta
from typing import List, Optional

from ..dominio.enums import NivelTriajeEnum
from ..dominio.modelos import ConsultaMedica, Medico
from .externos import BrokerWebRTCSimulado
from .infraestructura import Notificador, Reloj, Repositorio


class ServicioAgendamiento:
    MINUTOS_ALERTA_ESPERA = 30   # HU-14 / RF-11
    MINUTOS_INASISTENCIA = 15    # máquina de estados: after(15 min)
    DESFASE_CITA_MIN = {NivelTriajeEnum.III: 0, NivelTriajeEnum.IV: 30, NivelTriajeEnum.V: 120}

    def __init__(self, repo: Repositorio, broker: BrokerWebRTCSimulado, notificador: Notificador, reloj: Reloj):
        self.repo = repo
        self.broker = broker
        self.notificador = notificador
        self.reloj = reloj

    # ---------------------------------------------------------- médicos
    def carga(self, medico_id: str) -> int:
        return sum(1 for c in self.repo.consultas_en_estado("AGENDADA", "EN_CURSO") if c.medico_id == medico_id)

    def medico_candidato(self) -> Optional[Medico]:
        disponibles = [m for m in self.repo.medicos() if m.esta_disponible]
        if not disponibles:
            return None
        return min(disponibles, key=lambda m: (self.carga(m.id), m.nombre))

    # ------------------------------------------------------------ asignar
    def asignar(self, consulta: ConsultaMedica) -> bool:
        """Agenda con un médico disponible o deja la consulta en la lista de espera."""
        ahora = self.reloj.ahora()
        medico = self.medico_candidato()
        if medico is None:
            if consulta.nombre_estado != "EN_ESPERA":
                consulta.poner_en_espera(ahora)
                self.notificador.notificar(
                    consulta.paciente_id,
                    f"No hay médicos disponibles. Estás en la lista de espera (posición {self.posicion_en_espera(consulta)}).")
            return False
        _, url = self.broker.crear_sala_privada(consulta.id)
        fecha = ahora + timedelta(minutes=self.DESFASE_CITA_MIN.get(consulta.nivel, 0))
        consulta.agendar(medico.id, fecha, url, ahora)
        self.notificador.notificar(
            consulta.paciente_id,
            f"Cita confirmada con {medico.nombre} para las {fecha:%H:%M}. Ya tienes el enlace de la sala.", "ok")
        self.notificador.notificar(
            medico.id, f"Nueva cita (nivel {consulta.nivel.romano}) a las {fecha:%H:%M}. Revisa el resumen del triaje.")
        self._cerrar_alerta(consulta.id)
        return True

    # ------------------------------------------------------ lista de espera
    def lista_espera(self) -> List[ConsultaMedica]:
        return sorted(self.repo.consultas_en_estado("EN_ESPERA"),
                      key=lambda c: (c.nivel.value, c.en_espera_desde))

    def posicion_en_espera(self, consulta: ConsultaMedica) -> int:
        ids = [c.id for c in self.lista_espera()]
        return ids.index(consulta.id) + 1 if consulta.id in ids else 0

    def procesar_lista_espera(self) -> int:
        """Evento 'Médico disponible': asigna en orden de prioridad mientras haya médicos."""
        asignadas = 0
        for consulta in self.lista_espera():
            if not self.asignar(consulta):
                break
            asignadas += 1
        return asignadas

    def cola_de_medico(self, medico_id: str) -> List[ConsultaMedica]:
        mias = [c for c in self.repo.consultas_en_estado("AGENDADA", "EN_CURSO") if c.medico_id == medico_id]
        return sorted(mias, key=lambda c: (c.nivel.value, c.fecha_hora_creacion))

    # ---------------------------------------------------- temporizadores
    def revisar_alertas_espera(self) -> List[dict]:
        """HU-14: alerta si un paciente de nivel III lleva más de 30 minutos en espera."""
        ahora = self.reloj.ahora()
        limite = timedelta(minutes=self.MINUTOS_ALERTA_ESPERA)
        for consulta in self.lista_espera():
            vencida = consulta.nivel == NivelTriajeEnum.III and ahora - consulta.en_espera_desde > limite
            if vencida and not self._alerta_activa(consulta.id):
                minutos = int((ahora - consulta.en_espera_desde).total_seconds() // 60)
                self.repo.alertas_admin.append({"consulta_id": consulta.id, "desde": ahora, "activa": True,
                                                "minutos": minutos, "cerrada": None})
                consulta.registrar(ahora, f"Alerta de espera larga: {minutos} min en espera")
                self.notificador.notificar_administradores(
                    f"Paciente de nivel III lleva {minutos} min en espera (consulta {consulta.id}).")
        return [a for a in self.repo.alertas_admin if a["activa"]]

    def revisar_inasistencias(self) -> int:
        """after(15 min) [inasistencia] / marcarInasistencia()."""
        ahora = self.reloj.ahora()
        canceladas = 0
        for consulta in self.repo.consultas_en_estado("AGENDADA"):
            if ahora > consulta.fecha_hora_cita + timedelta(minutes=self.MINUTOS_INASISTENCIA):
                consulta.cancelar("Inasistencia: nadie entró a la sala en 15 minutos", ahora)
                self.notificador.notificar(consulta.paciente_id, "Tu cita se canceló por inasistencia.", "alerta")
                canceladas += 1
        return canceladas

    def _alerta_activa(self, consulta_id: str) -> bool:
        return any(a["consulta_id"] == consulta_id and a["activa"] for a in self.repo.alertas_admin)

    def _cerrar_alerta(self, consulta_id: str) -> None:
        for alerta in self.repo.alertas_admin:
            if alerta["consulta_id"] == consulta_id and alerta["activa"]:
                alerta["activa"] = False
                alerta["cerrada"] = self.reloj.ahora()
