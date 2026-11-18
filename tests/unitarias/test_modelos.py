"""Pruebas unitarias de las entidades del dominio."""
import pytest

from app.dominio.enums import NivelTriajeEnum, OrigenSignosEnum
from app.dominio.modelos import (DatoInvalido, ItemReceta, Medico, Paciente, RecetaDigital,
                                 SignosVitales, Sintoma, TriajeIA)
from tests.conftest import sintoma


class TestUsuario:
    def test_password_se_guarda_con_bcrypt_costo_10(self):
        p = Paciente("Ana", "ANA@demo.co", "secreta1", documento_id="1", consentimiento_datos=True)
        assert p.password_hash.startswith(b"$2b$10$")  # RNF-02
        assert b"secreta1" not in p.password_hash
        assert p.email == "ana@demo.co"

    def test_autenticar_correcta_e_incorrecta(self):
        p = Paciente("Ana", "ana@demo.co", "secreta1", documento_id="1", consentimiento_datos=True)
        assert p.autenticar("secreta1")
        assert not p.autenticar("otra")

    def test_usuario_desactivado_no_puede_entrar(self):
        m = Medico("Dr. X", "x@demo.co", "secreta1", registro_medico="RM-1")
        m.activo = False
        assert not m.autenticar("secreta1")

    def test_password_corta_no_se_permite(self):
        with pytest.raises(DatoInvalido):
            Paciente("Ana", "a@d.co", "123", documento_id="1", consentimiento_datos=True)

    def test_paciente_sin_consentimiento_no_se_registra(self):  # RNF-08
        with pytest.raises(DatoInvalido, match="1581"):
            Paciente("Ana", "a@d.co", "secreta1", documento_id="1", consentimiento_datos=False)

    def test_medico_requiere_registro(self):  # RF-10
        with pytest.raises(DatoInvalido):
            Medico("Dr. X", "x@d.co", "secreta1", registro_medico="")


class TestSintoma:
    @pytest.mark.parametrize("intensidad", [0, 11, -3])
    def test_intensidad_fuera_de_rango(self, intensidad):
        with pytest.raises(DatoInvalido):
            sintoma(intensidad=intensidad)

    def test_sintoma_vacio(self):
        with pytest.raises(DatoInvalido):
            Sintoma("   ", 1, 5)

    def test_horas_negativas(self):
        with pytest.raises(DatoInvalido):
            sintoma(horas=-1)

    def test_descripcion_de_mas_de_500(self):
        with pytest.raises(DatoInvalido):
            sintoma(descripcion="x" * 501)

    def test_limites_validos(self):
        assert sintoma(intensidad=1).intensidad == 1
        assert sintoma(intensidad=10, descripcion="x" * 500).intensidad == 10

    @pytest.mark.parametrize("texto", ["Dolor de pecho", "no puedo respirar bien", "tuve un desmayo"])
    def test_detecta_sintoma_critico(self, texto):
        assert sintoma(texto).es_sintoma_critico()

    def test_sintoma_normal_no_es_critico(self):
        assert not sintoma("Dolor de garganta").es_sintoma_critico()


class TestSignosVitales:
    def test_spo2_menor_a_90_es_bandera_roja(self):
        assert SignosVitales(80, 89.9, 36.5).es_bandera_roja_spo2()
        assert not SignosVitales(80, 90.0, 36.5).es_bandera_roja_spo2()

    @pytest.mark.parametrize("fc,spo2,temp,esperado", [
        (131, 97, 36.5, True), (39, 97, 36.5, True), (80, 97, 40.0, True),
        (130, 97, 39.9, False), (40, 90, 36.5, False)])
    def test_banderas_rojas(self, fc, spo2, temp, esperado):
        assert SignosVitales(fc, spo2, temp).es_bandera_roja() is esperado

    @pytest.mark.parametrize("fc,spo2,temp", [(10, 95, 36), (80, 101, 36), (80, 95, 50)])
    def test_rangos_imposibles(self, fc, spo2, temp):
        with pytest.raises(DatoInvalido):
            SignosVitales(fc, spo2, temp)

    def test_origen_por_defecto_es_sensor(self):
        assert SignosVitales(80, 97, 36.5).origen == OrigenSignosEnum.SENSOR


class TestTriajeYReceta:
    def test_nivel_final_del_medico_manda(self):
        t = TriajeIA(NivelTriajeEnum.IV, "x")
        assert t.nivel == NivelTriajeEnum.IV
        t.nivel_final_medico = NivelTriajeEnum.III
        assert t.nivel == NivelTriajeEnum.III

    def test_nivel_critico(self):
        assert TriajeIA(NivelTriajeEnum.II, "x").es_nivel_critico()
        assert not TriajeIA(NivelTriajeEnum.III, "x").es_nivel_critico()

    def test_enum_nivel(self):
        assert NivelTriajeEnum.IV.minutos_maximos_cita == 120
        assert NivelTriajeEnum.V.minutos_maximos_cita == 1440
        assert "urgencias" in NivelTriajeEnum.II.descripcion

    def test_receta_sin_items_no_se_permite(self):
        with pytest.raises(DatoInvalido):
            RecetaDigital("C", "M", "P", [])

    def test_item_incompleto(self):
        with pytest.raises(DatoInvalido):
            ItemReceta("Acetaminofén", "", "c/8h", "3 días")

    def test_codigo_qr_es_estable_y_unico(self):
        item = ItemReceta("Acetaminofén", "500 mg", "c/8h", "3 días")
        r1, r2 = RecetaDigital("C", "M", "P", [item]), RecetaDigital("C", "M", "P", [item])
        assert r1.generar_codigo_qr() == r1.generar_codigo_qr()
        assert r1.generar_codigo_qr() != r2.generar_codigo_qr()
        assert len(r1.generar_codigo_qr()) == 16
