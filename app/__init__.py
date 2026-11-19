"""Aplicación web de HealthPulse Telemedicina."""
import os
from datetime import timedelta

from flask import Flask

from .sistema import Sistema
from .web.rutas import registrar_rutas


def create_app(config=None):
    """Construye Flask, el sistema en memoria y registra las rutas."""
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "clave-local-de-desarrollo")
    # RNF-02: la sesión expira a los 15 minutos de inactividad.
    app.permanent_session_lifetime = timedelta(minutes=15)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # En la nube (HTTPS_ONLY=1) la cookie de sesión solo viaja por HTTPS.
    app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("HTTPS_ONLY"))
    if config:
        app.config.update(config)
    app.sistema = Sistema(semilla=app.config.get("SEMILLA"))
    registrar_rutas(app)
    return app
