"""Capa de dominio: entidades del diagrama de clases de diseño (Figura 7)."""
from __future__ import annotations

import hashlib
import uuid
from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

import bcrypt

from .enums import (EstadoEnvioRecetaEnum, EstadoMedicoEnum, NivelTriajeEnum,
                    OrigenSignosEnum, RolEnum)


class DatoInvalido(ValueError):
    """Se lanza cuando un dato ingresado no cumple las reglas (RF-02, RF-03)."""


def nuevo_id(prefijo: str) -> str:
    return f"{prefijo}-{uuid.uuid4().hex[:8].upper()}"


# ----------------------------------------------------------------- usuarios
class Usuario(ABC):
    """Clase abstracta: nadie es 'solo usuario'."""

    COSTO_BCRYPT = 10  # RNF-02: bcrypt con costo >= 10

    def __init__(self, nombre: str, email: str, password: str, rol: RolEnum, id: Optional[str] = None):
        self.id = id or nuevo_id("USR")
        self.nombre = nombre
        self.email = email.strip().lower()
        self._password_hash = self.hash_password(password)
        self.rol = rol
        self.activo = True

    @classmethod
    def hash_password(cls, password: str) -> bytes:
        if len(password) < 6:
            raise DatoInvalido("La contraseña debe tener al menos 6 caracteres.")
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=cls.COSTO_BCRYPT))

    @property
    def password_hash(self) -> bytes:
        return self._password_hash

    def autenticar(self, password: str) -> bool:
        return self.activo and bcrypt.checkpw(password.encode(), self._password_hash)


class Paciente(Usuario):
    def __init__(self, nombre, email, password, documento_id: str, telefono: str = "",
                 fecha_nacimiento: str = "", consentimiento_datos: bool = False, id=None):
        super().__init__(nombre, email, password, RolEnum.PACIENTE, id)
        if not consentimiento_datos:
            raise DatoInvalido("Debes aceptar el tratamiento de datos de salud (Ley 1581 de 2012).")
        self.documento_id = documento_id
        self.telefono = telefono
        self.fecha_nacimiento = fecha_nacimiento
        self.consentimiento_datos = consentimiento_datos


class Medico(Usuario):
    def __init__(self, nombre, email, password, registro_medico: str, especialidad: str = "Medicina general", id=None):
        super().__init__(nombre, email, password, RolEnum.MEDICO, id)
        if not registro_medico:
            raise DatoInvalido("El registro médico es obligatorio.")
        self.registro_medico = registro_medico
        self.especialidad = especialidad
        self.disponibilidad = EstadoMedicoEnum.DISPONIBLE

    def cambiar_disponibilidad(self, estado: EstadoMedicoEnum) -> None:
        self.disponibilidad = EstadoMedicoEnum(estado)

    @property
    def esta_disponible(self) -> bool:
        return self.activo and self.disponibilidad == EstadoMedicoEnum.DISPONIBLE


class Administrador(Usuario):
    def __init__(self, nombre, email, password, codigo_empleado: str, id=None):
        super().__init__(nombre, email, password, RolEnum.ADMINISTRADOR, id)
        self.codigo_empleado = codigo_empleado


# ------------------------------------------------------------ datos clínicos
PALABRAS_CRITICAS = (
    "dolor de pecho", "dolor en el pecho", "no puedo respirar", "dificultad para respirar",
    "desmayo", "convulsion", "convulsión", "sangrado abundante", "pérdida de conciencia",
    "perdida de conciencia", "parálisis", "paralisis", "cara caída", "peor dolor de cabeza",
    "dolor de cabeza súbito", "dolor de cabeza subito",
)


@dataclass
class Sintoma:
    sintoma_principal: str
    tiempo_evolucion_horas: float
    intensidad: int
    descripcion_libre: str = ""
    id: str = field(default_factory=lambda: nuevo_id("SIN"))

    def __post_init__(self):
        self.sintoma_principal = (self.sintoma_principal or "").strip()
        if not self.sintoma_principal:
            raise DatoInvalido("El síntoma principal es obligatorio.")
        if not 1 <= int(self.intensidad) <= 10:
            raise DatoInvalido("La intensidad debe estar entre 1 y 10.")
        if float(self.tiempo_evolucion_horas) < 0:
            raise DatoInvalido("El tiempo de evolución no puede ser negativo.")
        if len(self.descripcion_libre or "") > 500:
            raise DatoInvalido("La descripción no puede superar 500 caracteres.")
        self.intensidad = int(self.intensidad)
        self.tiempo_evolucion_horas = float(self.tiempo_evolucion_horas)

    def es_sintoma_critico(self) -> bool:
        texto = f"{self.sintoma_principal} {self.descripcion_libre}".lower()
        return any(p in texto for p in PALABRAS_CRITICAS)


@dataclass
class SignosVitales:
    frecuencia_cardiaca: int
    saturacion_o2: float
    temperatura: float
    origen: OrigenSignosEnum = OrigenSignosEnum.SENSOR
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not 20 <= int(self.frecuencia_cardiaca) <= 250:
            raise DatoInvalido("Frecuencia cardíaca fuera de rango (20 a 250 lpm).")
        if not 50 <= float(self.saturacion_o2) <= 100:
            raise DatoInvalido("Saturación de oxígeno fuera de rango (50 a 100 %).")
        if not 30 <= float(self.temperatura) <= 45:
            raise DatoInvalido("Temperatura fuera de rango (30 a 45 °C).")

    def es_bandera_roja_spo2(self) -> bool:
        return self.saturacion_o2 < 90

    def es_bandera_roja(self) -> bool:
        """SpO2 < 90 %, FC > 130 o < 40, o temperatura >= 40 °C."""
        fc_mala = self.frecuencia_cardiaca > 130 or self.frecuencia_cardiaca < 40
        return self.es_bandera_roja_spo2() or fc_mala or self.temperatura >= 40


@dataclass
class TriajeIA:
    nivel_sugerido_ia: NivelTriajeEnum
    explicacion_ia: str
    origen: str = "MotorIA"
    nivel_final_medico: Optional[NivelTriajeEnum] = None
    id: str = field(default_factory=lambda: nuevo_id("TRI"))

    @property
    def nivel(self) -> NivelTriajeEnum:
        return self.nivel_final_medico or self.nivel_sugerido_ia

    def es_nivel_critico(self) -> bool:
        return self.nivel.es_critico


# ------------------------------------------------------------------ receta
@dataclass
class ItemReceta:
    medicamento: str
    dosis: str
    frecuencia: str
    duracion: str

    def __post_init__(self):
        if not all(x.strip() for x in (self.medicamento, self.dosis, self.frecuencia, self.duracion)):
            raise DatoInvalido("Cada medicamento necesita nombre, dosis, frecuencia y duración.")


@dataclass
class RecetaDigital:
    consulta_id: str
    medico_id: str
    paciente_id: str
    items: List[ItemReceta]
    id: str = field(default_factory=lambda: nuevo_id("REC"))
    fecha_emision: datetime = field(default_factory=datetime.now)
    estado_envio: EstadoEnvioRecetaEnum = EstadoEnvioRecetaEnum.SIN_ENVIAR
    numero_pedido: Optional[str] = None
    intentos_envio: int = 0

    def __post_init__(self):
        if not self.items:
            raise DatoInvalido("La receta debe tener al menos un medicamento.")

    def generar_codigo_qr(self) -> str:
        """Código de verificación (lo que iría dentro del QR)."""
        base = f"{self.id}|{self.medico_id}|{self.paciente_id}|{self.fecha_emision.isoformat()}"
        return hashlib.sha256(base.encode()).hexdigest()[:16].upper()


# --------------------------------------------------------------- consulta
class ConsultaMedica:
    """Objeto de negocio principal. Su comportamiento depende de su estado (patrón State)."""

    def __init__(self, paciente_id: str, sintomas: List[Sintoma], ahora: datetime):
        from .estados import EstadoEnTriaje  # import local para evitar ciclo

        if not sintomas:
            raise DatoInvalido("La consulta necesita al menos un síntoma.")
        self.id = nuevo_id("CON")
        self.paciente_id = paciente_id
        self.sintomas = list(sintomas)
        self.signos_vitales: Optional[SignosVitales] = None
        self.triaje: Optional[TriajeIA] = None
        self.medico_id: Optional[str] = None
        self.fecha_hora_creacion = ahora
        self.fecha_hora_cita: Optional[datetime] = None
        self.fecha_inicio_video: Optional[datetime] = None
        self.en_espera_desde: Optional[datetime] = None
        self.sala_webrtc_url: Optional[str] = None
        self.receta: Optional[RecetaDigital] = None
        self.diagnostico: str = ""
        self.motivo_cancelacion: str = ""
        self.bitacora: List[tuple] = []
        self._estado = EstadoEnTriaje()
        self.registrar(ahora, "Consulta creada en estado EN_TRIAJE")

    # ---- bitácora
    def registrar(self, cuando: datetime, texto: str) -> None:
        self.bitacora.append((cuando, texto))

    # ---- estado
    @property
    def estado(self):
        return self._estado

    @property
    def nombre_estado(self) -> str:
        return self._estado.nombre

    def set_estado(self, nuevo_estado, cuando: datetime) -> None:
        anterior = self._estado.nombre
        self._estado = nuevo_estado
        self.registrar(cuando, f"Cambio de estado: {anterior} -> {nuevo_estado.nombre}")

    # ---- operaciones que se delegan al estado actual
    def agendar(self, medico_id: str, fecha: datetime, sala_url: str, ahora: datetime) -> None:
        self._estado.agendar(self, medico_id, fecha, sala_url, ahora)

    def poner_en_espera(self, ahora: datetime) -> None:
        self._estado.poner_en_espera(self, ahora)

    def remitir_urgencias(self, ahora: datetime) -> None:
        self._estado.remitir_urgencias(self, ahora)

    def iniciar_videollamada(self, ahora: datetime) -> None:
        self._estado.iniciar_videollamada(self, ahora)

    def finalizar(self, diagnostico: str, ahora: datetime) -> None:
        self._estado.finalizar(self, diagnostico, ahora)

    def cerrar(self, ahora: datetime) -> None:
        self._estado.cerrar(self, ahora)

    def cancelar(self, motivo: str, ahora: datetime) -> None:
        self._estado.cancelar(self, motivo, ahora)

    @property
    def nivel(self) -> Optional[NivelTriajeEnum]:
        return self.triaje.nivel if self.triaje else None
