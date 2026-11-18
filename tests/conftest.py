"""Datos y objetos compartidos por todas las pruebas."""
from datetime import datetime

import pytest

from app import create_app
from app.dominio.modelos import ConsultaMedica, Sintoma
from app.sistema import Sistema

AHORA = datetime(2026, 11, 20, 10, 0, 0)


@pytest.fixture
def sistema():
    return Sistema(semilla=42)


@pytest.fixture
def paciente(sistema):
    return sistema.repo.buscar_por_email("paciente@demo.co")


@pytest.fixture
def otro_paciente(sistema):
    return sistema.repo.buscar_por_email("paciente2@demo.co")


@pytest.fixture
def medico(sistema):
    return sistema.repo.buscar_por_email("medico@demo.co")


@pytest.fixture
def medico2(sistema):
    return sistema.repo.buscar_por_email("medico2@demo.co")


@pytest.fixture
def admin(sistema):
    return sistema.repo.buscar_por_email("admin@demo.co")


def sintoma(texto="Dolor de cabeza", horas=12, intensidad=5, descripcion=""):
    return Sintoma(texto, horas, intensidad, descripcion)


@pytest.fixture
def consulta():
    return ConsultaMedica("PAC-1", [sintoma()], AHORA)


@pytest.fixture
def app():
    return create_app({"TESTING": True, "SEMILLA": 7, "SECRET_KEY": "pruebas"})


@pytest.fixture
def cliente(app):
    return app.test_client()


def entrar(cliente, email, password="demo123"):
    return cliente.post("/login", data={"email": email, "password": password})
