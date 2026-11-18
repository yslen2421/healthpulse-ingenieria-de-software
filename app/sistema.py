"""Arma todas las piezas del sistema (como una pequeña 'fábrica')."""
from __future__ import annotations

from typing import Optional

from .dominio.modelos import Administrador, Medico, Paciente, Usuario
from .servicios.agendamiento import ServicioAgendamiento
from .servicios.consultas import ConsultaMedicaRealService, ConsultaMedicaSecurityProxy
from .servicios.externos import BrokerWebRTCSimulado, MotorIASimulado, SensorSignosVitalesSimulado
from .servicios.farmacia import FarmaciaLegacyAdapter, FarmaciaLegacyXMLClient
from .servicios.infraestructura import Notificador, Reloj, Repositorio
from .servicios.triaje import ServicioTriaje

CLAVE_DEMO = "demo123"


class Sistema:
    def __init__(self, semilla: Optional[int] = None, datos_demo: bool = True):
        self.reloj = Reloj()
        self.repo = Repositorio()
        self.notificador = Notificador(self.repo, self.reloj)
        self.sensor = SensorSignosVitalesSimulado(semilla)
        self.motor_ia = MotorIASimulado()
        self.broker = BrokerWebRTCSimulado()
        self.farmacia_legacy = FarmaciaLegacyXMLClient(semilla=semilla)
        self.farmacia = FarmaciaLegacyAdapter(self.farmacia_legacy)
        self.triaje = ServicioTriaje(self.motor_ia, self.sensor)
        self.agendamiento = ServicioAgendamiento(self.repo, self.broker, self.notificador, self.reloj)
        self.consultas = ConsultaMedicaRealService(self.repo, self.reloj, self.notificador,
                                                   self.triaje, self.agendamiento, self.farmacia)
        if datos_demo:
            self.cargar_datos_demo()

    def servicio_para(self, usuario: Optional[Usuario]) -> ConsultaMedicaSecurityProxy:
        """Todo acceso desde la web pasa por el Protection Proxy."""
        return ConsultaMedicaSecurityProxy(self.consultas, usuario)

    def cargar_datos_demo(self) -> None:
        """Usuarios ficticios para la demo. Ningún dato es real."""
        self.repo.guardar_usuario(Paciente("Laura Gómez (ficticia)", "paciente@demo.co", CLAVE_DEMO,
                                           documento_id="1000000001", telefono="3000000001",
                                           consentimiento_datos=True))
        self.repo.guardar_usuario(Paciente("Andrés Ruiz (ficticio)", "paciente2@demo.co", CLAVE_DEMO,
                                           documento_id="1000000002", consentimiento_datos=True))
        self.repo.guardar_usuario(Medico("Dra. Camila Rojas (ficticia)", "medico@demo.co", CLAVE_DEMO,
                                         registro_medico="RM-10001"))
        self.repo.guardar_usuario(Medico("Dr. Felipe Torres (ficticio)", "medico2@demo.co", CLAVE_DEMO,
                                         registro_medico="RM-10002"))
        self.repo.guardar_usuario(Administrador("Admin HealthPulse", "admin@demo.co", CLAVE_DEMO,
                                                codigo_empleado="ADM-01"))
