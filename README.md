# HealthPulse Telemedicina — Prototipo (Grupo 3)

Proyecto Final Integral · Ingeniería de Software I (PCIA5008) · Universidad Sergio Arboleda
Equipo: Yslen Natalia Moreno Gutiérrez (PO), Karla Mariana Duque Callejas (SM), Jorge Antonio García Romero (Dev)

Plataforma web de telemedicina: el paciente ingresa sus síntomas, un sensor de signos vitales **simulado** toma
FC, SpO2 y temperatura, un **MotorIA simulado** clasifica el triaje (niveles I a V), el sistema agenda una
videoconsulta (WebRTC con Jitsi Meet) con un médico disponible, el médico emite la receta digital y la receta se
envía a la **FarmaciaLegacy simulada** en XML. Todos los datos son ficticios.

## Documentos del proyecto

Todos los entregables (documento completo, cada entregable por separado, el documento de cada sesión y los diagramas) están en la carpeta [`documentos/`](documentos/).

- Aplicación en la nube: https://healthpulse-grupo3.onrender.com

## Patrones de diseño (los mismos del diagrama de clases de la Sesión 4)

| Patrón | Dónde está |
|---|---|
| State | `app/dominio/estados.py` — un estado por cada estado de la máquina de estados de ConsultaMedica |
| Protection Proxy | `app/servicios/consultas.py` — `ConsultaMedicaSecurityProxy` revisa el rol antes de llamar al servicio real |
| Adapter | `app/servicios/farmacia.py` — `FarmaciaLegacyAdapter` traduce `RecetaDigital` al XML del legacy |

## Estructura

```
app/
  dominio/      enums.py, modelos.py (entidades), estados.py (patrón State)
  servicios/    triaje.py, agendamiento.py, consultas.py (servicio + proxy), farmacia.py (adapter),
                externos.py (sensor, MotorIA y BrokerWebRTC simulados), infraestructura.py (reloj, repositorio)
  web/          rutas.py (pantallas de paciente, médico y administrador)
  templates/    páginas HTML
tests/
  unitarias/    159 pruebas (dominio, estados, triaje, adapter, proxy, agendamiento)
  integracion/  15 pruebas (flujo completo CU-02, RNF-07 con 40 casos de referencia, RNF-01)
  sistema/      26 pruebas (24 con el cliente web + 2 en navegador real con Playwright)
```

## Correr en local

```bash
python -m venv .venv
source .venv/bin/activate        # en Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python wsgi.py                   # abrir http://127.0.0.1:5000
```

Usuarios de prueba (contraseña `demo123`): `paciente@demo.co`, `paciente2@demo.co`, `medico@demo.co`,
`medico2@demo.co`, `admin@demo.co`.

## Pruebas y métricas

```bash
pytest --cov=app --cov-branch --cov-report=term-missing   # pruebas + cobertura
radon cc app -s -a                                        # complejidad ciclomática de McCabe por función
flake8 app tests                                          # estilo + max-complexity 10
# prueba en navegador real (con la app corriendo):
python -m playwright install chromium
E2E_URL=http://127.0.0.1:5000 pytest tests/sistema/test_e2e_navegador.py
```

## Desplegar en la nube (Render, gratis)

1. Crear una cuenta en GitHub (si no la tienen) y un repositorio nuevo, por ejemplo `healthpulse-grupo3`.
2. Subir esta carpeta al repositorio:
   ```bash
   git init && git add . && git commit -m "Prototipo HealthPulse Grupo 3"
   git branch -M main
   git remote add origin https://github.com/USUARIO/healthpulse-grupo3.git
   git push -u origin main
   ```
3. Entrar a https://render.com con la cuenta de GitHub → **New** → **Blueprint** → elegir el repositorio.
   Render lee el archivo `render.yaml` y crea el servicio `healthpulse-grupo3` solo.
4. Esperar el despliegue (2 a 4 minutos). La URL queda así: `https://healthpulse-grupo3.onrender.com`.
5. Revisar que `https://.../salud` responda `{"estado": "ok"}` y correr la prueba E2E contra la nube:
   `E2E_URL=https://healthpulse-grupo3.onrender.com pytest tests/sistema/test_e2e_navegador.py`
6. (Opcional, RNF-03) Crear un monitor gratis en https://uptimerobot.com apuntando a `/salud` cada 5 minutos.

Notas del plan gratuito de Render: el servicio "se duerme" tras 15 minutos sin visitas y tarda unos 50 segundos
en despertar; **abran la página unos minutos antes de la demo**. Como el prototipo guarda los datos en memoria,
cada vez que el servicio se reinicia vuelve a los usuarios de prueba (por eso se usa 1 worker en `render.yaml`).

## Guion corto para la demo (Sesión 6)

1. Paciente → Nueva consulta → escenario "Fiebre" → queda AGENDADA con sala de video.
2. Paciente → Nueva consulta → "Dificultad para respirar", escenario "Oxígeno bajo" → REMITIDA A URGENCIAS.
3. Médico → Atender → Iniciar videoconsulta → Finalizar con receta → CERRADA con número de pedido.
4. Administrador → Simular caída de la farmacia → repetir el paso 3 → receta PENDIENTE → Reenviar.
5. Administrador → "Desactivar" a los dos médicos → paciente hace un triaje de nivel III (queda EN_ESPERA) →
   administrador → "Adelantar 31 min" → aparece la alerta de espera larga (HU-14). Luego "Activar" a un médico: el
   paciente se le asigna solo y la alerta se cierra.
6. Paciente 2 intenta abrir la consulta del paciente 1 → "Acceso denegado" (Protection Proxy).
