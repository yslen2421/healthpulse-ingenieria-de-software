"""Patrón Adapter para la FarmaciaLegacy (simulada).

La farmacia del hospital es un sistema antiguo que solo entiende XML. Nuestro
sistema trabaja con objetos RecetaDigital. El adaptador traduce entre los dos.
"""
from __future__ import annotations

import random
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from ..dominio.enums import EstadoEnvioRecetaEnum
from ..dominio.modelos import RecetaDigital


class IFarmaciaService(ABC):
    @abstractmethod
    def enviar_receta(self, receta: RecetaDigital) -> bool:
        """Envía la receta y devuelve True si la farmacia la confirmó."""


@dataclass
class ResponseDTO:
    ok: bool
    numero_pedido: Optional[str] = None
    error: Optional[str] = None


class FarmaciaLegacyXMLClient:
    """Simula el servicio SOAP/XML antiguo de la farmacia del hospital."""

    def __init__(self, caida: bool = False, fallas_seguidas: int = 0, semilla: Optional[int] = None):
        self.caida = caida                  # la farmacia está totalmente caída
        self.fallas_seguidas = fallas_seguidas  # cuántas veces falla antes de responder bien
        self.recibidos = []
        self._rnd = random.Random(semilla)

    def post_receta_xml(self, xml_content: str) -> ResponseDTO:
        if self.caida:
            return ResponseDTO(False, error="Timeout de conexión con FarmaciaLegacy")
        if self.fallas_seguidas > 0:
            self.fallas_seguidas -= 1
            return ResponseDTO(False, error="Error 503 de FarmaciaLegacy")
        raiz = ET.fromstring(xml_content)  # el legacy valida que el XML esté bien formado
        if raiz.tag != "OrdenFarmacia" or raiz.find("Items") is None:
            return ResponseDTO(False, error="XML con formato inválido")
        self.recibidos.append(xml_content)
        return ResponseDTO(True, numero_pedido=f"PED-{self._rnd.randint(100000, 999999)}")


class FarmaciaLegacyAdapter(IFarmaciaService):
    MAX_INTENTOS = 3  # RF-08 y RNF-06

    def __init__(self, legacy_client: FarmaciaLegacyXMLClient):
        self.legacy_client = legacy_client

    def enviar_receta(self, receta: RecetaDigital) -> bool:
        xml = self._convertir_a_xml(receta)
        for _ in range(self.MAX_INTENTOS):  # loop del diagrama de secuencia
            receta.intentos_envio += 1
            respuesta = self.legacy_client.post_receta_xml(xml)
            if respuesta.ok:
                receta.estado_envio = EstadoEnvioRecetaEnum.CONFIRMADA
                receta.numero_pedido = respuesta.numero_pedido
                return True
        receta.estado_envio = EstadoEnvioRecetaEnum.PENDIENTE
        return False

    @staticmethod
    def _convertir_a_xml(receta: RecetaDigital) -> str:
        raiz = ET.Element("OrdenFarmacia", {"id": receta.id, "codigoVerificacion": receta.generar_codigo_qr()})
        ET.SubElement(raiz, "Paciente").text = receta.paciente_id
        ET.SubElement(raiz, "Medico").text = receta.medico_id
        ET.SubElement(raiz, "Fecha").text = receta.fecha_emision.strftime("%Y-%m-%dT%H:%M:%S")
        items = ET.SubElement(raiz, "Items")
        for item in receta.items:
            nodo = ET.SubElement(items, "Item")
            for campo in ("medicamento", "dosis", "frecuencia", "duracion"):
                ET.SubElement(nodo, campo.capitalize()).text = getattr(item, campo)
        return ET.tostring(raiz, encoding="unicode")
