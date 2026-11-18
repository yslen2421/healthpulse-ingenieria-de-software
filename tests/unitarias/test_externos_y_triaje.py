"""Pruebas unitarias del sensor simulado, el MotorIA simulado y el servicio de triaje."""
import pytest

from app.dominio.enums import NivelTriajeEnum, OrigenSignosEnum
from app.dominio.modelos import SignosVitales
from app.servicios.externos import (BrokerWebRTCSimulado, MotorIASimulado,
                                    SensorSignosVitalesSimulado, TiempoAgotado)
from app.servicios.triaje import ServicioTriaje
from tests.conftest import sintoma

N = NivelTriajeEnum


class TestSensor:
    @pytest.mark.parametrize("escenario", ["normal", "fiebre", "taquicardia", "hipoxia"])
    def test_lecturas_dentro_del_rango_del_escenario(self, escenario):
        sensor = SensorSignosVitalesSimulado(semilla=1)
        conf = sensor.ESCENARIOS[escenario]
        for _ in range(20):
            lectura, latencia = sensor.leer(escenario)
            assert conf["fc"][0] <= lectura.frecuencia_cardiaca <= conf["fc"][1]
            assert conf["spo2"][0] <= lectura.saturacion_o2 <= conf["spo2"][1]
            assert latencia <= 5
            assert lectura.origen == OrigenSignosEnum.SENSOR

    def test_falla_por_timeout_de_5_segundos(self):
        with pytest.raises(TiempoAgotado, match="5 s"):
            SensorSignosVitalesSimulado().leer("falla")

    def test_escenario_desconocido_usa_normal(self):
        lectura, _ = SensorSignosVitalesSimulado(semilla=3).leer("inventado")
        assert lectura.saturacion_o2 >= 95

    def test_misma_semilla_misma_lectura(self):
        a, _ = SensorSignosVitalesSimulado(semilla=9).leer()
        b, _ = SensorSignosVitalesSimulado(semilla=9).leer()
        assert (a.frecuencia_cardiaca, a.saturacion_o2) == (b.frecuencia_cardiaca, b.saturacion_o2)


class TestMotorIA:
    def setup_method(self):
        self.motor = MotorIASimulado()

    @pytest.mark.parametrize("intensidad,esperado", [(1, N.V), (4, N.IV), (8, N.III), (10, N.III)])
    def test_niveles_sin_signos(self, intensidad, esperado):
        nivel, explicacion = self.motor.clasificar([sintoma(intensidad=intensidad, horas=24)], None)
        assert nivel == esperado
        assert "sin signos vitales" in explicacion

    def test_sintoma_critico_sube_el_nivel(self):
        nivel, explicacion = self.motor.clasificar([sintoma("Dolor de pecho", horas=1, intensidad=8)], None)
        assert nivel == N.I
        assert "alarma" in explicacion

    def test_signos_alterados_suman_puntaje(self):
        signos = SignosVitales(115, 92, 38.5)
        nivel, explicacion = self.motor.clasificar([sintoma(intensidad=5, horas=24)], signos)
        assert nivel == N.III  # 25 (intensidad) + 10 (fiebre) + 10 (FC) + 15 (SpO2) = 60 puntos
        assert "fiebre" in explicacion and "SpO2 baja" in explicacion

    def test_puntaje_nunca_pasa_de_100(self):
        _, explicacion = self.motor.clasificar([sintoma("Dolor de pecho", 1, 10)], SignosVitales(140, 85, 39))
        assert "100/100" in explicacion

    def test_inicio_reciente_e_intenso(self):
        nivel, explicacion = self.motor.clasificar([sintoma(intensidad=7, horas=2)], None)
        assert "inicio reciente" in explicacion
        assert nivel == N.III

    def test_no_disponible_lanza_timeout(self):
        self.motor.disponible = False
        with pytest.raises(TiempoAgotado):
            self.motor.clasificar([sintoma()], None)

    def test_latencia_mayor_a_3s_es_timeout(self):
        self.motor.latencia_s = 3.5
        with pytest.raises(TiempoAgotado, match="3 s"):
            self.motor.clasificar([sintoma()], None)


class TestServicioTriaje:
    def setup_method(self):
        self.servicio = ServicioTriaje(MotorIASimulado(), SensorSignosVitalesSimulado(semilla=5))

    def test_tomar_signos_con_sensor(self):
        signos, nota = self.servicio.tomar_signos("sensor", "normal")
        assert signos.origen == OrigenSignosEnum.SENSOR
        assert "recibida" in nota

    def test_sensor_falla_y_usa_manual(self):
        signos, nota = self.servicio.tomar_signos("sensor", "falla", {"fc": "80", "spo2": "96", "temp": "36.8"})
        assert signos.origen == OrigenSignosEnum.MANUAL
        assert "a mano" in nota

    def test_sensor_falla_sin_manual_sigue_sin_signos(self):
        signos, nota = self.servicio.tomar_signos("sensor", "falla", {"fc": "", "spo2": "", "temp": ""})
        assert signos is None
        assert "sin signos" in nota

    def test_modo_manual_y_omitir(self):
        signos, _ = self.servicio.tomar_signos("manual", manual={"fc": 70, "spo2": 98, "temp": 36.5})
        assert signos.frecuencia_cardiaca == 70
        assert self.servicio.tomar_signos("manual", manual=None)[0] is None
        assert self.servicio.tomar_signos("omitir")[0] is None

    def test_bandera_roja_spo2_fuerza_nivel_critico(self):  # RF-04, RNF-07
        triaje = self.servicio.clasificar([sintoma(intensidad=2, horas=48)], SignosVitales(80, 88, 36.5))
        assert triaje.nivel_sugerido_ia in (N.I, N.II)
        assert "Bandera roja" in triaje.explicacion_ia

    def test_spo2_menor_a_85_es_nivel_I(self):
        triaje = self.servicio.clasificar([sintoma(intensidad=2, horas=48)], SignosVitales(80, 84, 36.5))
        assert triaje.nivel_sugerido_ia == N.I

    def test_sin_bandera_roja_respeta_a_la_ia(self):
        triaje = self.servicio.clasificar([sintoma(intensidad=4, horas=48)], SignosVitales(80, 97, 36.5))
        assert triaje.nivel_sugerido_ia == N.IV
        assert triaje.origen == "MotorIA"

    def test_ia_caida_usa_reglas_de_respaldo(self):  # after(3 s) / aplicarReglasRespaldo()
        self.servicio.motor.disponible = False
        triaje = self.servicio.clasificar([sintoma(intensidad=8)], None)
        assert triaje.origen == "Reglas de respaldo"
        assert triaje.nivel_sugerido_ia == N.III

    @pytest.mark.parametrize("intensidad,descripcion,esperado", [
        (9, "dolor de pecho", N.II), (7, "", N.III), (5, "", N.IV), (2, "", N.V)])
    def test_reglas_de_respaldo(self, intensidad, descripcion, esperado):
        nivel, _ = ServicioTriaje.reglas_respaldo([sintoma(intensidad=intensidad, descripcion=descripcion)], None)
        assert nivel == esperado


def test_broker_crea_salas_unicas_y_privadas():
    broker = BrokerWebRTCSimulado()
    s1, url1 = broker.crear_sala_privada("CON-1")
    s2, _ = broker.crear_sala_privada("CON-1")
    assert s1 != s2 and url1.startswith("https://meet.jit.si/HealthPulse-CON-1-")
    broker.disponible = False
    with pytest.raises(TiempoAgotado):
        broker.crear_sala_privada("CON-2")
