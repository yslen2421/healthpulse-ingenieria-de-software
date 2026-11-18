"""Servicio de consultas y Protection Proxy (control de acceso por rol, RBAC)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from ..dominio.enums import EstadoMedicoEnum, NivelTriajeEnum, RolEnum
from ..dominio.modelos import (ConsultaMedica, DatoInvalido, ItemReceta, RecetaDigital,
                               Sintoma, Usuario)
from .agendamiento import ServicioAgendamiento
from .farmacia import IFarmaciaService
from .infraestructura import Notificador, Reloj, Repositorio
from .triaje import ServicioTriaje


class AccesoDenegado(PermissionError):
    """El usuario no tiene permiso para esta operación."""


class ConsultaNoEncontrada(LookupError):
    pass


class IConsultaMedicaService(ABC):
    @abstractmethod
    def crear_consulta(self, paciente_id: str, sintoma: Sintoma) -> ConsultaMedica: ...

    @abstractmethod
    def realizar_triaje(self, consulta_id: str, modo_signos: str, escenario: str = "normal",
                        manual: Optional[dict] = None) -> ConsultaMedica: ...

    @abstractmethod
    def validar_triaje(self, consulta_id: str, nivel: NivelTriajeEnum) -> ConsultaMedica: ...

    @abstractmethod
    def acceder_sala_webrtc(self, consulta_id: str, usuario_id: str) -> str: ...

    @abstractmethod
    def iniciar_videollamada(self, consulta_id: str) -> ConsultaMedica: ...

    @abstractmethod
    def finalizar_consulta(self, consulta_id: str, diagnostico: str,
                           items: List[ItemReceta]) -> ConsultaMedica: ...

    @abstractmethod
    def reenviar_receta(self, consulta_id: str) -> bool: ...

    @abstractmethod
    def cancelar(self, consulta_id: str, motivo: str) -> ConsultaMedica: ...

    @abstractmethod
    def obtener(self, consulta_id: str) -> ConsultaMedica: ...


class ConsultaMedicaRealService(IConsultaMedicaService):
    def __init__(self, repo: Repositorio, reloj: Reloj, notificador: Notificador,
                 triaje: ServicioTriaje, agendamiento: ServicioAgendamiento, farmacia: IFarmaciaService):
        self.repo = repo
        self.reloj = reloj
        self.notificador = notificador
        self.triaje = triaje
        self.agendamiento = agendamiento
        self.farmacia = farmacia

    def obtener(self, consulta_id: str) -> ConsultaMedica:
        consulta = self.repo.consulta(consulta_id)
        if consulta is None:
            raise ConsultaNoEncontrada(f"No existe la consulta {consulta_id}.")
        return consulta

    # ------------------------------------------------------------- CU-02
    def crear_consulta(self, paciente_id: str, sintoma: Sintoma) -> ConsultaMedica:
        consulta = ConsultaMedica(paciente_id, [sintoma], self.reloj.ahora())
        return self.repo.guardar_consulta(consulta)

    def realizar_triaje(self, consulta_id, modo_signos, escenario="normal", manual=None):
        consulta = self.obtener(consulta_id)
        if consulta.nombre_estado != "EN_TRIAJE":
            raise DatoInvalido("El triaje ya se realizó para esta consulta.")
        signos, nota = self.triaje.tomar_signos(modo_signos, escenario, manual)
        consulta.signos_vitales = signos
        consulta.registrar(self.reloj.ahora(), nota)
        consulta.triaje = self.triaje.clasificar(consulta.sintomas, signos)
        consulta.registrar(self.reloj.ahora(),
                           f"Triaje nivel {consulta.nivel.romano} ({consulta.triaje.origen})")
        if consulta.triaje.es_nivel_critico():
            self._remitir_urgencias(consulta)
        else:
            self.agendamiento.asignar(consulta)
        return consulta

    def _remitir_urgencias(self, consulta: ConsultaMedica) -> None:
        consulta.remitir_urgencias(self.reloj.ahora())
        self.notificador.notificar(
            consulta.paciente_id,
            "Tu triaje es de nivel crítico. Dirígete a urgencias presenciales o llama a la línea 123.", "alerta")
        self.notificador.notificar_administradores(
            f"Consulta {consulta.id} remitida a urgencias (nivel {consulta.nivel.romano}).")
        consulta.registrar(self.reloj.ahora(), "Notificación de remisión enviada al paciente y al administrador")

    # ------------------------------------------------------------ médico
    def validar_triaje(self, consulta_id, nivel):
        consulta = self.obtener(consulta_id)
        if consulta.nombre_estado not in ("AGENDADA", "EN_CURSO"):
            raise DatoInvalido("Solo se puede validar el triaje de una consulta agendada o en curso.")
        consulta.triaje.nivel_final_medico = NivelTriajeEnum(int(nivel))
        consulta.registrar(self.reloj.ahora(), f"El médico validó el triaje en nivel {consulta.nivel.romano}")
        return consulta

    def acceder_sala_webrtc(self, consulta_id, usuario_id):
        consulta = self.obtener(consulta_id)
        if consulta.nombre_estado not in ("AGENDADA", "EN_CURSO"):
            raise DatoInvalido("La sala solo está abierta para consultas agendadas o en curso.")
        return consulta.sala_webrtc_url

    def iniciar_videollamada(self, consulta_id):
        consulta = self.obtener(consulta_id)
        consulta.iniciar_videollamada(self.reloj.ahora())
        self.repo.usuario(consulta.medico_id).cambiar_disponibilidad(EstadoMedicoEnum.OCUPADO)
        self.notificador.notificar(consulta.paciente_id, "Tu médico ya está en la sala. ¡Entra a la videoconsulta!", "ok")
        return consulta

    def finalizar_consulta(self, consulta_id, diagnostico, items):
        consulta = self.obtener(consulta_id)
        ahora = self.reloj.ahora()
        consulta.finalizar(diagnostico, ahora)
        medico = self.repo.usuario(consulta.medico_id)
        medico.cambiar_disponibilidad(EstadoMedicoEnum.DISPONIBLE)
        if items:
            consulta.receta = RecetaDigital(consulta.id, medico.id, consulta.paciente_id, items, fecha_emision=ahora)
            consulta.registrar(ahora, f"Receta {consulta.receta.id} emitida (código {consulta.receta.generar_codigo_qr()})")
            self._enviar_a_farmacia(consulta)
        else:
            consulta.cerrar(ahora)
        self.agendamiento.procesar_lista_espera()
        return consulta

    def _enviar_a_farmacia(self, consulta: ConsultaMedica) -> bool:
        receta = consulta.receta
        ok = self.farmacia.enviar_receta(receta)
        ahora = self.reloj.ahora()
        if ok:
            consulta.registrar(ahora, f"Farmacia confirmó el pedido {receta.numero_pedido} "
                                      f"en {receta.intentos_envio} intento(s)")
            consulta.cerrar(ahora)
            self.notificador.notificar(consulta.paciente_id,
                                       f"Tu receta llegó a la farmacia. Pedido {receta.numero_pedido}.", "ok")
        else:
            consulta.registrar(ahora, f"Farmacia sin respuesta tras {receta.intentos_envio} intentos: receta PENDIENTE")
            self.notificador.notificar(consulta.paciente_id,
                                       "Tu receta quedó pendiente de envío a la farmacia. La reenviaremos pronto.", "alerta")
            self.notificador.notificar_administradores(f"Receta {receta.id} pendiente de envío a la farmacia.")
        return ok

    def reenviar_receta(self, consulta_id):
        consulta = self.obtener(consulta_id)
        if consulta.receta is None or consulta.nombre_estado != "FINALIZADA":
            raise DatoInvalido("No hay una receta pendiente para esta consulta.")
        return self._enviar_a_farmacia(consulta)

    def cancelar(self, consulta_id, motivo):
        consulta = self.obtener(consulta_id)
        consulta.cancelar(motivo, self.reloj.ahora())
        self.agendamiento._cerrar_alerta(consulta.id)
        return consulta


class ConsultaMedicaSecurityProxy(IConsultaMedicaService):
    """Misma interfaz que el servicio real, pero revisa el rol y la relación con la consulta."""

    def __init__(self, real_service: ConsultaMedicaRealService, usuario: Optional[Usuario]):
        self.real_service = real_service
        self.usuario = usuario

    # ---------------------------------------------------------- permisos
    def _verificar_permiso(self, *roles: RolEnum) -> None:
        if self.usuario is None or not self.usuario.activo:
            raise AccesoDenegado("Debes iniciar sesión.")
        if self.usuario.rol not in roles:
            raise AccesoDenegado("Tu rol no tiene permiso para esta operación.")

    def _verificar_participante(self, consulta_id: str, *, permitir_admin: bool = False) -> ConsultaMedica:
        consulta = self.real_service.obtener(consulta_id)
        uid = self.usuario.id
        if uid in (consulta.paciente_id, consulta.medico_id):
            return consulta
        if permitir_admin and self.usuario.rol == RolEnum.ADMINISTRADOR:
            return consulta
        raise AccesoDenegado("Esta consulta no es tuya.")

    def _verificar_medico_asignado(self, consulta_id: str) -> None:
        self._verificar_permiso(RolEnum.MEDICO)
        if self.real_service.obtener(consulta_id).medico_id != self.usuario.id:
            raise AccesoDenegado("Solo el médico asignado puede hacer esto.")

    def _verificar_paciente_dueno(self, consulta_id: str) -> None:
        self._verificar_permiso(RolEnum.PACIENTE)
        if self.real_service.obtener(consulta_id).paciente_id != self.usuario.id:
            raise AccesoDenegado("Esta consulta no es tuya.")

    # -------------------------------------------------------- operaciones
    def crear_consulta(self, paciente_id, sintoma):
        self._verificar_permiso(RolEnum.PACIENTE)
        if paciente_id != self.usuario.id:
            raise AccesoDenegado("Solo puedes crear consultas para ti.")
        return self.real_service.crear_consulta(paciente_id, sintoma)

    def realizar_triaje(self, consulta_id, modo_signos, escenario="normal", manual=None):
        self._verificar_paciente_dueno(consulta_id)
        return self.real_service.realizar_triaje(consulta_id, modo_signos, escenario, manual)

    def validar_triaje(self, consulta_id, nivel):
        self._verificar_medico_asignado(consulta_id)
        return self.real_service.validar_triaje(consulta_id, nivel)

    def acceder_sala_webrtc(self, consulta_id, usuario_id):
        self._verificar_permiso(RolEnum.PACIENTE, RolEnum.MEDICO)
        if usuario_id != self.usuario.id:
            raise AccesoDenegado("No puedes pedir la sala a nombre de otra persona.")
        self._verificar_participante(consulta_id)
        return self.real_service.acceder_sala_webrtc(consulta_id, usuario_id)

    def iniciar_videollamada(self, consulta_id):
        self._verificar_medico_asignado(consulta_id)
        return self.real_service.iniciar_videollamada(consulta_id)

    def finalizar_consulta(self, consulta_id, diagnostico, items):
        self._verificar_medico_asignado(consulta_id)
        return self.real_service.finalizar_consulta(consulta_id, diagnostico, items)

    def reenviar_receta(self, consulta_id):
        self._verificar_permiso(RolEnum.ADMINISTRADOR)
        return self.real_service.reenviar_receta(consulta_id)

    def cancelar(self, consulta_id, motivo):
        self._verificar_permiso(RolEnum.PACIENTE, RolEnum.ADMINISTRADOR)
        self._verificar_participante(consulta_id, permitir_admin=True)
        return self.real_service.cancelar(consulta_id, motivo)

    def obtener(self, consulta_id):
        self._verificar_permiso(RolEnum.PACIENTE, RolEnum.MEDICO, RolEnum.ADMINISTRADOR)
        return self._verificar_participante(consulta_id, permitir_admin=True)
