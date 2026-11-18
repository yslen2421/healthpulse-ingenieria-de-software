"""Pruebas unitarias del patrón Adapter con la FarmaciaLegacy simulada."""
import xml.etree.ElementTree as ET

import pytest

from app.dominio.enums import EstadoEnvioRecetaEnum
from app.dominio.modelos import ItemReceta, RecetaDigital
from app.servicios.farmacia import FarmaciaLegacyAdapter, FarmaciaLegacyXMLClient, IFarmaciaService


@pytest.fixture
def receta():
    return RecetaDigital("CON-1", "MED-1", "PAC-1", [
        ItemReceta("Acetaminofén", "500 mg", "cada 8 horas", "3 días"),
        ItemReceta("Loratadina", "10 mg", "cada 24 horas", "5 días")])


def test_adapter_cumple_la_interfaz():
    assert isinstance(FarmaciaLegacyAdapter(FarmaciaLegacyXMLClient()), IFarmaciaService)


def test_convierte_la_receta_a_xml_del_legacy(receta):
    xml = FarmaciaLegacyAdapter._convertir_a_xml(receta)
    raiz = ET.fromstring(xml)
    assert raiz.tag == "OrdenFarmacia"
    assert raiz.get("id") == receta.id
    assert raiz.get("codigoVerificacion") == receta.generar_codigo_qr()
    items = raiz.find("Items").findall("Item")
    assert len(items) == 2
    assert items[0].find("Medicamento").text == "Acetaminofén"


def test_envio_exitoso_al_primer_intento(receta):
    cliente = FarmaciaLegacyXMLClient(semilla=1)
    assert FarmaciaLegacyAdapter(cliente).enviar_receta(receta)
    assert receta.estado_envio == EstadoEnvioRecetaEnum.CONFIRMADA
    assert receta.numero_pedido.startswith("PED-")
    assert receta.intentos_envio == 1
    assert len(cliente.recibidos) == 1


def test_reintenta_y_confirma_al_tercer_intento(receta):
    cliente = FarmaciaLegacyXMLClient(fallas_seguidas=2)
    assert FarmaciaLegacyAdapter(cliente).enviar_receta(receta)
    assert receta.intentos_envio == 3


def test_tres_fallas_deja_la_receta_pendiente(receta):  # RNF-06: 0 recetas perdidas
    cliente = FarmaciaLegacyXMLClient(caida=True)
    assert not FarmaciaLegacyAdapter(cliente).enviar_receta(receta)
    assert receta.estado_envio == EstadoEnvioRecetaEnum.PENDIENTE
    assert receta.intentos_envio == 3
    assert receta.numero_pedido is None


def test_legacy_rechaza_xml_con_formato_invalido():
    respuesta = FarmaciaLegacyXMLClient().post_receta_xml("<Otro><Nada/></Otro>")
    assert not respuesta.ok and "inválido" in respuesta.error
