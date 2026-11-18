"""Reloj, repositorio en memoria y notificaciones.

El reloj se puede adelantar para la demo (por ejemplo, para mostrar la alerta de
30 minutos de espera o la inasistencia de 15 minutos sin esperar de verdad).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from ..dominio.enums import RolEnum
from ..dominio.modelos import ConsultaMedica, Medico, Usuario


class Reloj:
    def __init__(self):
        self._desfase = timedelta(0)

    def ahora(self) -> datetime:
        return datetime.now() + self._desfase

    def adelantar(self, minutos: int) -> None:
        self._desfase += timedelta(minutes=minutos)

    def reiniciar(self) -> None:
        self._desfase = timedelta(0)


class Repositorio:
    """Guarda todo en memoria (para el prototipo). En producción sería una base de datos."""

    def __init__(self):
        self.usuarios: Dict[str, Usuario] = {}
        self.consultas: Dict[str, ConsultaMedica] = {}
        self.notificaciones: Dict[str, List[dict]] = {}
        self.alertas_admin: List[dict] = []

    # usuarios
    def guardar_usuario(self, usuario: Usuario) -> Usuario:
        if self.buscar_por_email(usuario.email) and self.buscar_por_email(usuario.email).id != usuario.id:
            raise ValueError("Ya existe un usuario con ese correo.")
        self.usuarios[usuario.id] = usuario
        return usuario

    def buscar_por_email(self, email: str) -> Optional[Usuario]:
        email = email.strip().lower()
        return next((u for u in self.usuarios.values() if u.email == email), None)

    def usuario(self, usuario_id: str) -> Optional[Usuario]:
        return self.usuarios.get(usuario_id)

    def medicos(self) -> List[Medico]:
        return [u for u in self.usuarios.values() if u.rol == RolEnum.MEDICO]

    def administradores(self) -> List[Usuario]:
        return [u for u in self.usuarios.values() if u.rol == RolEnum.ADMINISTRADOR]

    # consultas
    def guardar_consulta(self, consulta: ConsultaMedica) -> ConsultaMedica:
        self.consultas[consulta.id] = consulta
        return consulta

    def consulta(self, consulta_id: str) -> Optional[ConsultaMedica]:
        return self.consultas.get(consulta_id)

    def consultas_de_paciente(self, paciente_id: str) -> List[ConsultaMedica]:
        lista = [c for c in self.consultas.values() if c.paciente_id == paciente_id]
        return sorted(lista, key=lambda c: c.fecha_hora_creacion, reverse=True)

    def consultas_en_estado(self, *estados: str) -> List[ConsultaMedica]:
        return [c for c in self.consultas.values() if c.nombre_estado in estados]


class Notificador:
    def __init__(self, repo: Repositorio, reloj: Reloj):
        self.repo = repo
        self.reloj = reloj

    def notificar(self, usuario_id: str, mensaje: str, tipo: str = "info") -> None:
        self.repo.notificaciones.setdefault(usuario_id, []).insert(
            0, {"fecha": self.reloj.ahora(), "mensaje": mensaje, "tipo": tipo})

    def notificar_administradores(self, mensaje: str, tipo: str = "alerta") -> None:
        for admin in self.repo.administradores():
            self.notificar(admin.id, mensaje, tipo)
