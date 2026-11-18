"""Pruebas de aceptación de requerimientos no funcionales que se pueden medir en local.

RNF-07: con un conjunto de casos clínicos FICTICIOS con nivel de referencia
(escrito por el equipo según la Resolución 5596 de 2015), el 100 % de los casos
con bandera roja debe quedar en nivel I o II y la sensibilidad para casos
críticos debe ser >= 95 %.

RNF-01: medición preliminar del tiempo del triaje dentro del servidor
(p95 <= 2 s y p99 <= 3 s). La prueba de carga con 200 usuarios sobre la nube
queda para la Sesión 6.
"""
import csv
import statistics
import time
from pathlib import Path

from app.dominio.modelos import SignosVitales, Sintoma
from app.servicios.externos import MotorIASimulado, SensorSignosVitalesSimulado
from app.servicios.triaje import ServicioTriaje

CASOS = Path(__file__).parent / "casos_referencia_triaje.csv"


def cargar_casos():
    with open(CASOS, encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            signos = None
            if fila["fc"]:
                signos = SignosVitales(int(fila["fc"]), float(fila["spo2"]), float(fila["temp"]))
            sintoma = Sintoma(fila["sintoma"], float(fila["horas"]), int(fila["intensidad"]), fila["descripcion"])
            yield fila, sintoma, signos


def clasificar_todos():
    servicio = ServicioTriaje(MotorIASimulado(), SensorSignosVitalesSimulado(semilla=1))
    resultados = []
    for fila, sintoma, signos in cargar_casos():
        triaje = servicio.clasificar([sintoma], signos)
        resultados.append((fila, triaje.nivel_sugerido_ia.value, servicio.hay_bandera_roja([sintoma], signos)))
    return resultados


def test_rnf07_banderas_rojas_100_por_ciento():
    resultados = clasificar_todos()
    con_bandera = [(f, n) for f, n, bandera in resultados if bandera]
    assert len(con_bandera) >= 10
    assert all(n <= 2 for _, n in con_bandera)


def test_rnf07_sensibilidad_casos_criticos():
    resultados = clasificar_todos()
    criticos = [(f, n) for f, n, _ in resultados if int(f["nivel_referencia"]) <= 2]
    detectados = sum(1 for _, n in criticos if n <= 2)
    sensibilidad = detectados / len(criticos)
    assert sensibilidad >= 0.95, f"Sensibilidad {sensibilidad:.0%}"


def test_rnf07_exactitud_general_informativa():
    """No es un umbral del RNF; se reporta en el informe de calidad."""
    resultados = clasificar_todos()
    exactos = sum(1 for f, n, _ in resultados if n == int(f["nivel_referencia"]))
    a_un_nivel = sum(1 for f, n, _ in resultados if abs(n - int(f["nivel_referencia"])) <= 1)
    assert a_un_nivel / len(resultados) >= 0.9
    assert exactos / len(resultados) >= 0.6


def test_rnf01_tiempo_del_triaje_en_servidor():
    servicio = ServicioTriaje(MotorIASimulado(), SensorSignosVitalesSimulado(semilla=1))
    casos = list(cargar_casos())
    tiempos = []
    for i in range(1000):
        _, sintoma, signos = casos[i % len(casos)]
        inicio = time.perf_counter()
        servicio.clasificar([sintoma], signos)
        tiempos.append(time.perf_counter() - inicio)
    q = statistics.quantiles(tiempos, n=100)
    assert q[94] <= 2.0 and q[98] <= 3.0
