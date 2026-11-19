"""Pantallas de paciente, médico y administrador."""
from __future__ import annotations

from flask import (abort, current_app, flash, g, redirect, render_template, request, session,
                   url_for)

from ..dominio.enums import EstadoEnvioRecetaEnum, EstadoMedicoEnum, NivelTriajeEnum, RolEnum
from ..dominio.estados import TransicionInvalida
from ..dominio.modelos import DatoInvalido, ItemReceta, Paciente, Sintoma
from ..servicios.consultas import AccesoDenegado, ConsultaNoEncontrada

RUTAS = []
PANELES = {
    RolEnum.PACIENTE: "panel_paciente",
    RolEnum.MEDICO: "panel_medico",
    RolEnum.ADMINISTRADOR: "panel_admin",
}


def sistema():
    return current_app.sistema


def servicio():
    return sistema().servicio_para(getattr(g, "usuario", None))


def requiere_rol(*roles):
    def envolver(funcion):
        funcion._roles = roles
        return funcion
    return envolver


def volver(usuario):
    """Redirige al panel que corresponde al rol. Sin sesión, vuelve al inicio."""
    if usuario is None:
        return redirect(url_for("inicio"))
    return redirect(url_for(PANELES[usuario.rol]))


def leer_items_receta(formulario):
    items = []
    for i in range(1, 4):
        medicamento = (formulario.get(f"medicamento{i}") or "").strip()
        dosis = (formulario.get(f"dosis{i}") or "").strip()
        frecuencia = (formulario.get(f"frecuencia{i}") or "").strip()
        duracion = (formulario.get(f"duracion{i}") or "").strip()
        if medicamento or dosis or frecuencia or duracion:
            items.append(ItemReceta(medicamento, dosis, frecuencia, duracion))
    return items


def estadisticas(repo):
    consultas = list(repo.consultas.values())
    con_triaje = [c for c in consultas if c.triaje]
    por_nivel = [(nivel.romano, sum(1 for c in con_triaje if c.nivel == nivel)) for nivel in NivelTriajeEnum]
    duraciones = [(c.fecha_inicio_video - c.fecha_hora_creacion).total_seconds() / 60
                  for c in consultas if c.fecha_inicio_video]
    promedio = round(sum(duraciones) / len(duraciones), 1) if duraciones else None
    return {"total": len(con_triaje), "por_nivel": por_nivel, "promedio_min": promedio}


def _ruta(regla, metodos=("GET",)):
    def envolver(funcion):
        RUTAS.append((regla, funcion, metodos))
        return funcion
    return envolver


def registrar_rutas(app):
    app.before_request(cargar_usuario_y_temporizadores)
    app.context_processor(datos_comunes)
    app.register_error_handler(403, acceso_denegado)
    app.register_error_handler(404, no_encontrado)
    for regla, vista, metodos in RUTAS:
        app.add_url_rule(regla, vista.__name__, vista, methods=metodos)


def cargar_usuario_y_temporizadores():
    uid = session.get("uid")
    g.usuario = sistema().repo.usuario(uid) if uid else None
    if g.usuario is not None and not g.usuario.activo:
        session.clear()
        g.usuario = None
    sistema().agendamiento.revisar_alertas_espera()
    sistema().agendamiento.revisar_inasistencias()
    vista = current_app.view_functions.get(request.endpoint or "")
    roles = getattr(vista, "_roles", None)
    if not roles:
        return None
    if g.usuario is None:
        return redirect(url_for("inicio"))
    if g.usuario.rol not in roles:
        abort(403)
    return None


def datos_comunes():
    usuario = getattr(g, "usuario", None)
    return {"usuario": usuario, "Rol": RolEnum}


def acceso_denegado(_error):
    return render_template("error.html", titulo="Acceso denegado",
                           mensaje="No tienes permiso para ver esta página."), 403


def no_encontrado(_error):
    return render_template("error.html", titulo="No encontrado",
                           mensaje="No encontramos lo que buscas."), 404


@_ruta("/salud")
def salud():
    return {"estado": "ok"}


@_ruta("/")
def inicio():
    if g.usuario:
        return volver(g.usuario)
    return render_template("inicio.html")


@_ruta("/login", ("POST",))
def login():
    usuario = sistema().repo.buscar_por_email(request.form.get("email", ""))
    password = request.form.get("password", "")
    if usuario is None or not usuario.autenticar(password):
        flash("Correo o contraseña incorrectos.", "error")
        return redirect(url_for("inicio"))
    session.clear()
    session["uid"] = usuario.id
    session.permanent = True
    return volver(usuario)


@_ruta("/logout")
def logout():
    session.clear()
    return redirect(url_for("inicio"))


@_ruta("/registro", ("GET", "POST"))
def registro():
    if request.method == "GET":
        return render_template("registro.html")
    datos = request.form
    try:
        if sistema().repo.buscar_por_email(datos.get("email", "")):
            raise DatoInvalido("Ya existe un usuario con ese correo.")
        paciente = Paciente(datos.get("nombre", ""), datos.get("email", ""), datos.get("password", ""),
                            documento_id=datos.get("documento", ""), telefono=datos.get("telefono", ""),
                            consentimiento_datos=datos.get("consentimiento") == "si")
        sistema().repo.guardar_usuario(paciente)
    except (DatoInvalido, ValueError) as error:
        flash(str(error), "error")
        return render_template("registro.html", datos=datos), 400
    session.clear()
    session["uid"] = paciente.id
    session.permanent = True
    return redirect(url_for("panel_paciente"))


@_ruta("/paciente")
@requiere_rol(RolEnum.PACIENTE)
def panel_paciente():
    consultas = sistema().repo.consultas_de_paciente(g.usuario.id)
    return render_template("paciente.html", consultas=consultas)


@_ruta("/paciente/nueva")
@requiere_rol(RolEnum.PACIENTE)
def nueva_consulta():
    return render_template("nueva_consulta.html")


@_ruta("/paciente/nueva", ("POST",))
@requiere_rol(RolEnum.PACIENTE)
def crear_consulta():
    datos = request.form
    try:
        sintoma = Sintoma(datos.get("sintoma", ""), datos.get("horas") or 0,
                          datos.get("intensidad") or 0, datos.get("descripcion") or "")
        manual = {"fc": datos.get("fc"), "spo2": datos.get("spo2"), "temp": datos.get("temp")}
        consulta = servicio().crear_consulta(g.usuario.id, sintoma)
        servicio().realizar_triaje(consulta.id, datos.get("modo_signos") or "sensor",
                                   datos.get("escenario") or "normal", manual)
    except (DatoInvalido, ValueError, AccesoDenegado) as error:
        flash(str(error), "error")
        return render_template("nueva_consulta.html", datos=datos), 400
    return redirect(url_for("ver_consulta", consulta_id=consulta.id))


@_ruta("/consulta/<consulta_id>")
@requiere_rol(RolEnum.PACIENTE, RolEnum.MEDICO, RolEnum.ADMINISTRADOR)
def ver_consulta(consulta_id):
    try:
        consulta = servicio().obtener(consulta_id)
    except ConsultaNoEncontrada:
        abort(404)
    except AccesoDenegado:
        abort(403)
    sala = None
    if consulta.nombre_estado in ("AGENDADA", "EN_CURSO") and g.usuario.rol != RolEnum.ADMINISTRADOR:
        try:
            sala = servicio().acceder_sala_webrtc(consulta.id, g.usuario.id)
        except (DatoInvalido, AccesoDenegado):
            sala = None
    medico = sistema().repo.usuario(consulta.medico_id) if consulta.medico_id else None
    return render_template(
        "consulta.html", c=consulta, medico=medico, paciente=sistema().repo.usuario(consulta.paciente_id),
        sala=sala, posicion=sistema().agendamiento.posicion_en_espera(consulta), niveles=list(NivelTriajeEnum))


def _actuar(consulta_id, accion):
    try:
        accion()
    except (DatoInvalido, TransicionInvalida, AccesoDenegado) as error:
        flash(str(error), "error")
    except ConsultaNoEncontrada:
        abort(404)
    return redirect(url_for("ver_consulta", consulta_id=consulta_id))


@_ruta("/consulta/<consulta_id>/cancelar", ("POST",))
@requiere_rol(RolEnum.PACIENTE, RolEnum.ADMINISTRADOR)
def cancelar_consulta(consulta_id):
    motivo = request.form.get("motivo") or "El paciente canceló"
    return _actuar(consulta_id, lambda: servicio().cancelar(consulta_id, motivo))


@_ruta("/consulta/<consulta_id>/validar", ("POST",))
@requiere_rol(RolEnum.MEDICO)
def validar_triaje(consulta_id):
    nivel = request.form.get("nivel")
    return _actuar(consulta_id, lambda: servicio().validar_triaje(consulta_id, nivel))


@_ruta("/consulta/<consulta_id>/iniciar", ("POST",))
@requiere_rol(RolEnum.MEDICO)
def iniciar_videollamada(consulta_id):
    return _actuar(consulta_id, lambda: servicio().iniciar_videollamada(consulta_id))


@_ruta("/consulta/<consulta_id>/finalizar", ("POST",))
@requiere_rol(RolEnum.MEDICO)
def finalizar_consulta(consulta_id):
    def accion():
        items = leer_items_receta(request.form)
        servicio().finalizar_consulta(consulta_id, request.form.get("diagnostico", ""), items)
    return _actuar(consulta_id, accion)


@_ruta("/medico")
@requiere_rol(RolEnum.MEDICO)
def panel_medico():
    repo = sistema().repo
    atendidas = [c for c in repo.consultas.values()
                 if c.medico_id == g.usuario.id and c.nombre_estado in ("FINALIZADA", "CERRADA")]
    atendidas.sort(key=lambda c: c.fecha_hora_creacion, reverse=True)
    return render_template(
        "medico.html", cola=sistema().agendamiento.cola_de_medico(g.usuario.id), atendidas=atendidas,
        espera=len(sistema().agendamiento.lista_espera()), repo=repo,
        notificaciones=repo.notificaciones.get(g.usuario.id, []))


@_ruta("/medico/disponibilidad", ("POST",))
@requiere_rol(RolEnum.MEDICO)
def cambiar_disponibilidad():
    estado = EstadoMedicoEnum(request.form.get("estado", "DISPONIBLE"))
    g.usuario.cambiar_disponibilidad(estado)
    if estado == EstadoMedicoEnum.DISPONIBLE:
        asignadas = sistema().agendamiento.procesar_lista_espera()
        if asignadas:
            texto = "paciente" if asignadas == 1 else "pacientes"
            flash(f"Se asignaron {asignadas} {texto} de la lista de espera.", "ok")
    return redirect(url_for("panel_medico"))


@_ruta("/admin")
@requiere_rol(RolEnum.ADMINISTRADOR)
def panel_admin():
    repo = sistema().repo
    pendientes = [c for c in repo.consultas.values()
                  if c.receta and c.receta.estado_envio == EstadoEnvioRecetaEnum.PENDIENTE]
    recientes = sorted(repo.consultas.values(), key=lambda c: c.fecha_hora_creacion, reverse=True)[:12]
    return render_template(
        "admin.html", stats=estadisticas(repo), espera=sistema().agendamiento.lista_espera(),
        alertas=sistema().agendamiento.revisar_alertas_espera(), pendientes=pendientes, recientes=recientes,
        medicos=repo.medicos(), ahora=sistema().reloj.ahora(), s=sistema(),
        notificaciones=repo.notificaciones.get(g.usuario.id, []))


@_ruta("/admin/reenviar/<consulta_id>", ("POST",))
@requiere_rol(RolEnum.ADMINISTRADOR)
def reenviar_receta(consulta_id):
    try:
        ok = servicio().reenviar_receta(consulta_id)
    except DatoInvalido as error:
        flash(str(error), "error")
    except ConsultaNoEncontrada:
        abort(404)
    except AccesoDenegado as error:
        flash(str(error), "error")
    else:
        if ok:
            flash("La farmacia confirmó la receta.", "ok")
        else:
            flash("La farmacia sigue sin responder. La receta continúa pendiente.", "alerta")
    return redirect(url_for("panel_admin"))


@_ruta("/admin/medico/<medico_id>/activo", ("POST",))
@requiere_rol(RolEnum.ADMINISTRADOR)
def activar_medico(medico_id):
    medico = sistema().repo.usuario(medico_id)
    if medico is None or medico.rol != RolEnum.MEDICO:
        abort(404)
    medico.activo = not medico.activo
    if medico.activo:
        asignadas = sistema().agendamiento.procesar_lista_espera()
        flash(f"Médico activado. Pacientes tomados de la lista de espera: {asignadas}.", "ok")
    else:
        flash(f"{medico.nombre} quedó desactivado.", "info")
    return redirect(url_for("panel_admin"))


@_ruta("/admin/simulador", ("POST",))
@requiere_rol(RolEnum.ADMINISTRADOR)
def simulador():
    s = sistema()
    accion = request.form.get("accion")
    if accion == "farmacia_toggle":
        s.farmacia_legacy.caida = not s.farmacia_legacy.caida
    elif accion == "ia_toggle":
        s.motor_ia.disponible = not s.motor_ia.disponible
    elif accion == "reloj_16":
        s.reloj.adelantar(16)
    elif accion == "reloj_31":
        s.reloj.adelantar(31)
    elif accion == "reloj_reset":
        s.reloj.reiniciar()
    else:
        abort(400)
    return redirect(url_for("panel_admin"))
