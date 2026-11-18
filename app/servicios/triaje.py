"""Lógica del triaje (lo que en el diagrama de secuencia hace ControllerTriaje)."""
from __future__ import annotations

from typing import Optional, Tuple

from ..dominio.enums import NivelTriajeEnum, OrigenSignosEnum
from ..dominio.modelos import SignosVitales, TriajeIA
from .externos import MotorIASimulado, SensorSignosVitalesSimulado, TiempoAgotado


class ServicioTriaje:
    def __init__(self, motor: MotorIASimulado, sensor: SensorSignosVitalesSimulado):
        self.motor = motor
        self.sensor = sensor

    # -------------------------------------------------------- signos vitales
    def tomar_signos(self, modo: str, escenario: str = "normal",
                     manual: Optional[dict] = None) -> Tuple[Optional[SignosVitales], str]:
        """modo: 'sensor', 'manual' u 'omitir'. Devuelve (signos o None, nota para la bitácora)."""
        if modo == "sensor":
            try:
                lectura, latencia = self.sensor.leer(escenario)
                return lectura, f"Lectura del sensor simulado recibida en {latencia:.1f} s"
            except TiempoAgotado as error:
                signos = self._signos_manuales(manual)
                nota = "se usaron los signos ingresados a mano" if signos else "se continúa sin signos"
                return signos, f"{error} Ruta alternativa: {nota}"
        if modo == "manual":
            signos = self._signos_manuales(manual)
            return signos, "Signos vitales ingresados a mano" if signos else "Sin signos vitales"
        return None, "El paciente omitió los signos vitales"

    @staticmethod
    def _signos_manuales(manual: Optional[dict]) -> Optional[SignosVitales]:
        if not manual or not all(manual.get(k) not in (None, "") for k in ("fc", "spo2", "temp")):
            return None
        return SignosVitales(int(manual["fc"]), float(manual["spo2"]), float(manual["temp"]),
                             origen=OrigenSignosEnum.MANUAL)

    # ------------------------------------------------------------ clasificar
    def clasificar(self, sintomas, signos: Optional[SignosVitales]) -> TriajeIA:
        try:
            nivel, explicacion = self.motor.clasificar(sintomas, signos)
            origen = "MotorIA"
        except TiempoAgotado as error:
            nivel, explicacion = self.reglas_respaldo(sintomas, signos)
            explicacion = f"{error} Se aplicaron las reglas de respaldo: {explicacion}"
            origen = "Reglas de respaldo"
        nivel, explicacion = self.aplicar_banderas_rojas(nivel, explicacion, sintomas, signos)
        return TriajeIA(nivel_sugerido_ia=nivel, explicacion_ia=explicacion, origen=origen)

    @staticmethod
    def hay_bandera_roja(sintomas, signos: Optional[SignosVitales]) -> bool:
        return any(s.es_sintoma_critico() for s in sintomas) or bool(signos and signos.es_bandera_roja())

    def aplicar_banderas_rojas(self, nivel, explicacion, sintomas, signos):
        """RF-04 y RNF-07: con una bandera roja el nivel es I o II, diga lo que diga la IA."""
        if not self.hay_bandera_roja(sintomas, signos):
            return nivel, explicacion
        if signos and signos.saturacion_o2 < 85:
            nuevo = NivelTriajeEnum.I
        else:
            nuevo = min(nivel, NivelTriajeEnum.II, key=lambda n: n.value)
        if nuevo != nivel:
            explicacion += f" Bandera roja detectada: el nivel sube de {nivel.romano} a {nuevo.romano}."
        return nuevo, explicacion

    @staticmethod
    def reglas_respaldo(sintomas, signos) -> Tuple[NivelTriajeEnum, str]:
        """Reglas conservadoras cuando la IA no responde: es mejor sobre-triar que sub-triar."""
        intensidad = max(s.intensidad for s in sintomas)
        if ServicioTriaje.hay_bandera_roja(sintomas, signos):
            return NivelTriajeEnum.II, "hay una bandera roja"
        if intensidad >= 7:
            return NivelTriajeEnum.III, f"intensidad {intensidad}/10"
        if intensidad >= 4:
            return NivelTriajeEnum.IV, f"intensidad {intensidad}/10"
        return NivelTriajeEnum.V, f"intensidad {intensidad}/10"
