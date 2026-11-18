"""Enumeraciones del dominio (valores fijos que no cambian)."""
from enum import Enum


class RolEnum(str, Enum):
    PACIENTE = "PACIENTE"
    MEDICO = "MEDICO"
    ADMINISTRADOR = "ADMINISTRADOR"


class EstadoMedicoEnum(str, Enum):
    DISPONIBLE = "DISPONIBLE"
    OCUPADO = "OCUPADO"
    DESCONECTADO = "DESCONECTADO"


class OrigenSignosEnum(str, Enum):
    SENSOR = "sensor"
    MANUAL = "manual"


class EstadoEnvioRecetaEnum(str, Enum):
    SIN_ENVIAR = "SIN_ENVIAR"
    CONFIRMADA = "CONFIRMADA"
    PENDIENTE = "PENDIENTE"


class NivelTriajeEnum(int, Enum):
    """Niveles de triaje (Resolución 5596 de 2015). I es el más grave."""

    I = 1  # noqa: E741  (número romano del nivel)
    II = 2
    III = 3
    IV = 4
    V = 5

    @property
    def romano(self) -> str:
        return self.name

    @property
    def es_critico(self) -> bool:
        return self.value <= 2

    @property
    def minutos_maximos_cita(self) -> int:
        """Tiempo máximo para la cita según RF-05 (III inmediata, IV 2 h, V 24 h)."""
        return {1: 0, 2: 0, 3: 0, 4: 120, 5: 1440}[self.value]

    @property
    def descripcion(self) -> str:
        return {
            1: "Resucitación: atención inmediata presencial",
            2: "Emergencia: urgencias presenciales",
            3: "Urgencia: videoconsulta inmediata",
            4: "Urgencia menor: videoconsulta en máximo 2 horas",
            5: "No urgente: videoconsulta en máximo 24 horas",
        }[self.value]
