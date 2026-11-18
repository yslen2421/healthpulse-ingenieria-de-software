"""Sistemas externos SIMULADOS: sensor de signos vitales, MotorIA y BrokerWebRTC.

No tenemos el hardware ni el servicio real, así que los simulamos por software.
Cada simulador tiene un 'escenario' para poder mostrar en la demo los casos
normales y los casos de falla (timeouts).
"""
from __future__ import annotations

import random
import secrets
from typing import Iterable, Optional, Tuple

from ..dominio.enums import NivelTriajeEnum, OrigenSignosEnum
from ..dominio.modelos import SignosVitales, Sintoma


class TiempoAgotado(Exception):
    """El sistema externo no respondió dentro del tiempo máximo."""


# ------------------------------------------------------------------ sensor
class SensorSignosVitalesSimulado:
    """<<device>> Simula un oxímetro/termómetro que entrega FC, SpO2 y temperatura."""

    TIMEOUT_S = 5.0
    ESCENARIOS = {
        "normal": {"fc": (65, 95), "spo2": (95, 99), "temp": (36.2, 37.2), "latencia": 1.2},
        "fiebre": {"fc": (95, 118), "spo2": (93, 97), "temp": (38.3, 39.4), "latencia": 1.5},
        "taquicardia": {"fc": (135, 150), "spo2": (92, 96), "temp": (36.8, 37.6), "latencia": 1.0},
        "hipoxia": {"fc": (105, 125), "spo2": (84, 89), "temp": (37.0, 38.0), "latencia": 1.3},
        "falla": {"latencia": 7.0},  # no responde a tiempo
    }

    def __init__(self, semilla: Optional[int] = None):
        self._rnd = random.Random(semilla)

    def leer(self, escenario: str = "normal") -> Tuple[SignosVitales, float]:
        """Devuelve (lectura, latencia_simulada). Lanza TiempoAgotado si pasa de 5 s."""
        conf = self.ESCENARIOS.get(escenario, self.ESCENARIOS["normal"])
        latencia = conf["latencia"]
        if latencia > self.TIMEOUT_S:
            raise TiempoAgotado(f"El sensor no respondió en {self.TIMEOUT_S:.0f} s.")
        lectura = SignosVitales(
            frecuencia_cardiaca=self._rnd.randint(*conf["fc"]),
            saturacion_o2=round(self._rnd.uniform(*conf["spo2"]), 1),
            temperatura=round(self._rnd.uniform(*conf["temp"]), 1),
            origen=OrigenSignosEnum.SENSOR,
        )
        return lectura, latencia


# ---------------------------------------------------------------- MotorIA
class MotorIASimulado:
    """<<external system>> Simula el motor de IA con un modelo de puntaje ponderado.

    Calcula un puntaje de gravedad con la intensidad, el tiempo de evolución,
    palabras de alarma y los signos vitales, y lo convierte en nivel I a V.
    En una versión real este servicio sería un modelo entrenado; la interfaz
    (clasificar) se mantiene igual.
    """

    TIMEOUT_S = 3.0

    def __init__(self, disponible: bool = True, latencia_s: float = 0.4):
        self.disponible = disponible
        self.latencia_s = latencia_s

    def clasificar(self, sintomas: Iterable[Sintoma], signos: Optional[SignosVitales]) -> Tuple[NivelTriajeEnum, str]:
        if not self.disponible or self.latencia_s > self.TIMEOUT_S:
            raise TiempoAgotado(f"El MotorIA no respondió en {self.TIMEOUT_S:.0f} s.")
        sintomas = list(sintomas)
        puntaje, razones = self._puntaje_sintomas(sintomas)
        p_signos, r_signos = self._puntaje_signos(signos)
        puntaje = min(puntaje + p_signos, 100)  # la escala es de 0 a 100
        razones += r_signos
        nivel = self._nivel_desde_puntaje(puntaje)
        explicacion = f"Puntaje de gravedad {puntaje}/100. " + ("; ".join(razones) or "Sin hallazgos de alarma") + "."
        return nivel, explicacion

    @staticmethod
    def _puntaje_sintomas(sintomas) -> Tuple[int, list]:
        intensidad = max(s.intensidad for s in sintomas)
        puntaje = intensidad * 5
        razones = [f"intensidad máxima {intensidad}/10"]
        if any(s.es_sintoma_critico() for s in sintomas):
            puntaje += 45
            razones.append("síntoma de alarma en la descripción")
        if min(s.tiempo_evolucion_horas for s in sintomas) <= 6 and intensidad >= 7:
            puntaje += 10
            razones.append("inicio reciente e intenso")
        return puntaje, razones

    @staticmethod
    def _puntaje_signos(signos: Optional[SignosVitales]) -> Tuple[int, list]:
        if signos is None:
            return 0, ["sin signos vitales"]
        puntaje, razones = 0, []
        if signos.temperatura >= 38:
            puntaje += 10
            razones.append(f"fiebre {signos.temperatura} °C")
        if signos.frecuencia_cardiaca > 110:
            puntaje += 10
            razones.append(f"FC elevada {signos.frecuencia_cardiaca} lpm")
        if signos.saturacion_o2 < 94:
            puntaje += 15
            razones.append(f"SpO2 baja {signos.saturacion_o2} %")
        return puntaje, razones

    @staticmethod
    def _nivel_desde_puntaje(puntaje: int) -> NivelTriajeEnum:
        limites = ((90, NivelTriajeEnum.I), (75, NivelTriajeEnum.II), (35, NivelTriajeEnum.III),
                   (20, NivelTriajeEnum.IV))
        for minimo, nivel in limites:
            if puntaje >= minimo:
                return nivel
        return NivelTriajeEnum.V


# ----------------------------------------------------------- BrokerWebRTC
class BrokerWebRTCSimulado:
    """<<external system>> Crea salas privadas de video.

    Usamos Jitsi Meet (WebRTC, gratis y sin instalar nada) con un nombre de sala
    aleatorio e imposible de adivinar. El acceso al enlace lo controla nuestro
    Protection Proxy: solo el paciente y el médico de la cita lo pueden ver.
    """

    BASE_URL = "https://meet.jit.si/"

    def __init__(self, disponible: bool = True):
        self.disponible = disponible

    def crear_sala_privada(self, consulta_id: str) -> Tuple[str, str]:
        if not self.disponible:
            raise TiempoAgotado("El BrokerWebRTC no está disponible.")
        sala_id = f"HealthPulse-{consulta_id}-{secrets.token_urlsafe(9)}"
        return sala_id, self.BASE_URL + sala_id
