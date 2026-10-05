# EcoRuta Backend API

API FastAPI para gestionar nodos (contenedores), lecturas de sensores, usuarios, reportes ciudadanos y predicción de llenado de EcoRuta Trujillo. Usa SQLAlchemy con PostgreSQL/PostGIS (en Docker) y JWT para autenticar a las personas.

## Reparto de partes

| Parte | Tema | Responsable asignado | Rama | Estado |
|---|---|---|---|---|
| B | Reportes ciudadanos y roles | Anthony Mantilla | `feature/mantilla-reportes` | Implementada y probada |
| D | Predicción y tiempo real | Daniel | `feature/daniel-prediccion` | Implementada y probada |
| A | Camiones y rutas | Diego | Otra rama | No incluida en este README |
| C | Optimizador de rutas | Erwin | Otra rama | No incluida en este README |

Las partes B y D fueron avanzadas por Mantilla. La Parte D se dejó en la rama de Daniel. Cada parte tiene su sección más abajo, y la sección "Archivos compartidos entre las dos ramas" explica dónde pueden chocar al fusionarse.

## Puesta en marcha

Con Docker Desktop abierto, desde la raíz del proyecto en PowerShell:

```powershell
docker compose up -d db
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

En el `.env`:
- `DATABASE_URL=postgresql+psycopg2://ecoruta:ecoruta123@localhost:5433/ecoruta_db` (la plantilla puede traer un valor genérico; usa este).
- `SECRET_KEY` y `DEVICE_API_KEY`: genera una cadena distinta para cada una con `python -c "import secrets; print(secrets.token_hex(32))"`. No las compartas ni las subas a Git.

Después:

```powershell
python crear_tablas.py
uvicorn app.main:app --reload
```

La documentación interactiva queda en `http://127.0.0.1:8000/docs` (botón **Authorize** para iniciar sesión).

Para probar los endpoints protegidos hace falta un usuario por rol (`municipalidad`, `conductor`, `ciudadano`). `POST /auth/registro` solo crea ciudadanos; los otros roles se crean con el script de usuarios del equipo o directamente en la base.

## Endpoints y protección

Estado esperado una vez integradas las dos ramas.

| Método | Ruta | Quién puede usarlo | Parte |
|---|---|---|---|
| GET | `/` | Público | Base |
| POST | `/auth/registro` | Público (crea siempre ciudadanos) | Base |
| POST | `/auth/login` | Público | Base |
| GET | `/auth/me` | Cualquier usuario con sesión válida | Base |
| GET | `/nodos/` | `municipalidad`, `conductor` | B |
| POST | `/nodos/` | `municipalidad` | B |
| GET | `/nodos/{id}/lecturas` | `municipalidad`, `conductor` | B |
| GET | `/nodos/{id}/prediccion` | `municipalidad`, `conductor` | D |
| POST | `/lecturas/` | Dispositivo con `X-API-Key` válida | B |
| GET | `/panel/estado` | `municipalidad`, `conductor` | B |
| GET | `/panel/criticos` | `municipalidad`, `conductor` | B |
| GET | `/panel/resumen` | `municipalidad`, `conductor` | B |
| POST | `/reportes` | `ciudadano` | B |
| GET | `/reportes` | `municipalidad` (filtro `estado`, `limit`, `offset`) | B |
| PATCH | `/reportes/{id}` | `municipalidad` | B |
| WebSocket | `/ws/panel` | JWT de usuario activo con rol `municipalidad` o `conductor` | D |

Sin token la respuesta es 401, con un rol no autorizado 403, y con datos inválidos 422.

---

# Parte B: Reportes ciudadanos y roles

**Responsable asignado:** Anthony Mantilla · **Rama:** `feature/mantilla-reportes`

Los ciudadanos pueden reportar puntos críticos, y se cerró la protección por rol que faltaba en los endpoints de nodos, lecturas y panel.

## Archivos agregados o modificados

| Archivo | Estado | Qué hace |
|---|---|---|
| `app/models/reporte.py` | Nuevo | Define `ReporteCiudadano`, los estados `pendiente` y `atendido`, y la tabla `reportes_ciudadanos` con índices por usuario y estado. |
| `app/schemas/reporte.py` | Nuevo | Valida los datos para crear, listar y actualizar reportes (coordenadas, URL, descripción, filtro de estado). |
| `app/routers/reportes.py` | Nuevo | Crea reportes (ciudadano), los lista con filtro (municipalidad) y los marca como atendidos. |
| `tests/test_reportes.py` | Nuevo | Pruebas con pytest de schemas, estado del PATCH, serialización de usuarios y `require_roles`, sin base de datos. |
| `requirements-dev.txt` | Nuevo | Declara pytest como dependencia de desarrollo, separada de `requirements.txt`. |
| `pruebas/ecoruta-reportes-thunder.json` | Nuevo | Colección importable de Thunder Client con casos de éxito, 401, 403 y 422, usando variables. |
| `scripts/verificar_reportes_api.py` | Nuevo | Prueba la API por HTTP; genera los JWT desde la base, sin pedir contraseñas. |
| `app/main.py` | Modificado | Importa e incluye el router de reportes. |
| `crear_tablas.py` | Modificado | Importa el modelo nuevo para que `create_all` cree su tabla. |
| `app/routers/nodos.py` | Modificado | `GET /nodos/` exige municipalidad o conductor; `POST /nodos/` exige municipalidad. |
| `app/routers/lecturas.py` | Modificado | `POST /lecturas/` exige `X-API-Key`; el historial exige municipalidad o conductor. |
| `app/routers/panel.py` | Modificado | Aplica municipalidad/conductor a las tres rutas del panel. |
| `app/schemas/usuario.py` | Modificado | `UsuarioOut.email` pasó de `EmailStr` a `str` para poder responder con cuentas de prueba de dominio `.test`. El registro sigue validando con `EmailStr`. |
| `simulador/simulador.py` | Modificado | Inicia sesión como municipalidad para registrar nodos y envía `X-API-Key` en cada lectura. |
| `.env.example` | Modificado | Añade `SIMULADOR_EMAIL` y `SIMULADOR_PASSWORD` con valores de ejemplo. |

## Cómo encajan las piezas

El ciudadano crea un reporte con `POST /reportes` y queda como `pendiente`. La municipalidad lo consulta, con filtro opcional por estado, en `GET /reportes` y lo marca como atendido con `PATCH /reportes/{id}`. Repetir el PATCH sobre un reporte ya atendido responde 200 sin cambios, y un id inexistente responde 404.

Las personas usan sesión Bearer con permisos por rol. Los sensores no inician sesión: envían `X-API-Key`, por lo que **ya no existe el `POST /lecturas/` sin clave**. El simulador se adaptó: obtiene el token municipal desde `/auth/login` para registrar nodos y usa `DEVICE_API_KEY` al enviar lecturas.

## Ejecutar las pruebas

Con el entorno virtual activo y la API y la base en marcha:

```powershell
pip install -r requirements-dev.txt
python -m pytest -q
python scripts\verificar_reportes_api.py
```

El script HTTP necesita `DATABASE_URL`, `SECRET_KEY`, `DEVICE_API_KEY` y `ECORUTA_API_URL` (por ejemplo `http://127.0.0.1:8000`). Deja un reporte y un nodo de prueba en la base local.

## Colección de Thunder Client

Importa `pruebas/ecoruta-reportes-thunder.json` con **Import**. Crea un Environment local con `baseUrl`, `municipalidadToken`, `conductorToken`, `ciudadanoToken`, `deviceApiKey`, `reporteId`, `nodoId`, `codigoNodoExistente` y `nuevoCodigo`. Obtén los tokens con `/auth/login` y guárdalos solo en el Environment local, nunca en el JSON. Ejecuta primero la creación del reporte para obtener `reporteId`.

## Variables del simulador

`SIMULADOR_EMAIL` y `SIMULADOR_PASSWORD` son las credenciales de una cuenta activa de rol `municipalidad`, con las que el simulador inicia sesión en `/auth/login`. `DEVICE_API_KEY` debe ser igual a la clave del servidor y se envía en el encabezado `X-API-Key`.

```powershell
python -m simulador.simulador
```

---

# Parte D: Predicción y tiempo real

**Responsable asignado:** Daniel · **Rama:** `feature/daniel-prediccion`

Estima cuándo cada contenedor llegará a su nivel crítico y avisa al panel en tiempo real, sin recargar la página.

## Archivos agregados o modificados

| Archivo | Estado | Qué hace |
|---|---|---|
| `app/core/connection_manager.py` | Nuevo | Mantiene las conexiones WebSocket activas, reparte los mensajes y elimina a los clientes cuyo envío falla. |
| `app/core/estado_nodo.py` | Nuevo | Calcula `sin_datos`, `normal`, `alerta` o `critico` según el llenado y el umbral. Lo usan el panel y los eventos, para que digan siempre lo mismo. |
| `app/schemas/prediccion.py` | Nuevo | Define y valida la respuesta de predicción, incluidos método y confianza entre 0 y 1. |
| `app/services/prediccion_service.py` | Nuevo | Carga el modelo con caché y estima las horas hasta el umbral. Si no hay modelo, usa la tasa lineal; si no hay tasa positiva, devuelve estimación nula. |
| `ml/prediccion/features.py` | Nuevo | Ordena las lecturas, calcula las features, detecta vaciados (caídas de al menos 20 puntos) y construye etiquetas solo cuando el cruce del umbral se observa. Lo comparten el entrenamiento y el servicio. |
| `ml/prediccion/entrenar_modelo.py` | Nuevo | Lee las lecturas de PostgreSQL, separa por tiempo, excluye los objetivos censurados, compara LightGBM con la línea base lineal y guarda el modelo. |
| `scripts/ws_panel_client.py` | Nuevo | Cliente de consola que se conecta a `/ws/panel` con un JWT y muestra los mensajes. |
| `tests/test_features_prediccion.py` | Nuevo | Prueba vaciados, reinicio de la tasa y etiquetas observadas o censuradas. |
| `tests/test_prediccion_service.py` | Nuevo | Prueba el respaldo lineal y los casos crítico, sin lecturas y tasa cero o negativa. |
| `requirements-dev.txt` | Nuevo | Fija la versión de pytest para las pruebas. |
| `app/services/__init__.py`, `ml/__init__.py`, `ml/prediccion/__init__.py` | Nuevos | Marcan los directorios como paquetes de Python; no tienen lógica. |
| `app/main.py` | Modificado | Registra `/ws/panel`, valida el JWT y limita la conexión a usuarios activos con rol municipalidad o conductor. |
| `app/routers/nodos.py` | Modificado | Agrega `GET /nodos/{id}/prediccion`; responde 404 si el nodo no existe. |
| `app/routers/panel.py` | Modificado | Usa el cálculo de estado compartido en vez de una segunda implementación. |
| `app/routers/lecturas.py` | Modificado | Tras guardar una lectura, envía en segundo plano `lectura_nueva` y, si cambió la clasificación, `estado_cambiado`. Un fallo del aviso no impide guardar la lectura. |
| `.gitignore` | Modificado | Excluye `ml/prediccion/modelos/` (el modelo se regenera). |
| `requirements.txt` | Modificado | Añade las dependencias de predicción y WebSocket. Pasó de UTF-16 a UTF-8 sin BOM. |

Líneas nuevas en `requirements.txt`:

```text
joblib==1.5.2
lightgbm==4.6.0
numpy==2.3.3
pandas==2.3.3
scikit-learn==1.7.2
websockets==15.0.1
```

## Cómo encajan las piezas

Una lectura llega por `POST /lecturas/`, se guarda, se calcula su estado con la función compartida y se avisa a los clientes conectados a `/ws/panel`. Por otro lado, el entrenamiento genera el modelo que usa el servicio para `GET /nodos/{id}/prediccion`. Si no hay un modelo aplicable, el servicio usa el respaldo lineal e indica en la respuesta qué método usó.

Los estados usan los mismos literales que `/panel/estado`: `normal`, `alerta`, `critico` y `sin_datos`.

## Generar historial de prueba

Con el servidor activo (`uvicorn app.main:app --reload`), en otra terminal:

```powershell
python -m simulador.simulador
```

Déjalo correr varios minutos y detenlo con `Ctrl+C`. Con la Parte B integrada, el simulador necesita `SIMULADOR_EMAIL`, `SIMULADOR_PASSWORD` y `DEVICE_API_KEY`. Los datos sintéticos validan el flujo, pero no representan el comportamiento del piloto real.

## Entrenar o actualizar el modelo

```powershell
python -m ml.prediccion.entrenar_modelo
```

Hacen falta al menos 50 objetivos observables, con una división temporal de al menos 30 ejemplos de entrenamiento y 10 de validación. Si faltan, el comando indica cuántos hacen falta y no guarda un modelo nuevo. El modelo se guarda en `ml/prediccion/modelos/` y se reemplaza al volver a entrenar. Hay que volver a ejecutarlo cuando haya más lecturas, incluidos los datos del piloto real.

Limitaciones conocidas:
- Se excluyen las lecturas cuyo cruce del umbral no se observa antes de un vaciado o del fin del historial; el entrenamiento informa cuántas y qué porcentaje. El MAE solo describe los periodos observados.
- LightGBM y la línea base lineal se evalúan sobre las mismas observaciones. Con los datos del simulador, que llena casi en línea recta, LightGBM no supera a la línea base; la comparación real requiere datos del piloto.
- La confianza devuelta es una heurística, no una probabilidad calibrada.

## Consultar una predicción

En `/docs`, autentícate con un usuario `municipalidad` o `conductor` y llama a `GET /nodos/{id}/prediccion`. Devuelve horas y fecha estimadas, el método (`modelo` o `lineal`) y la confianza. Si el nodo no tiene lecturas, está estable o acaba de vaciarse, `horas_estimadas` y `fecha_estimada_critico` son `null`.

## Probar el WebSocket

Con el servidor activo, en otra terminal:

```powershell
python scripts\ws_panel_client.py
```

Pega el JWT de un usuario municipal o conductor cuando lo pida. Luego envía una lectura desde el simulador o con `POST /lecturas/`; el cliente muestra `lectura_nueva` y, si cambia la clasificación, `estado_cambiado`.

## Ejecutar las pruebas

```powershell
pip install -r requirements-dev.txt
python -m pytest -q
```

---

# Archivos compartidos entre las dos ramas

Las dos ramas salen del mismo `main` y modifican estos archivos. Al fusionar, hay que conservar los cambios de ambas.
| Archivo | Parte B | Parte D |
|---|---|---|
| `app/main.py` | Incluye el router `reportes` | Agrega la ruta `/ws/panel` |
| `app/routers/lecturas.py` | `verify_device_key` en `POST /lecturas/` y `require_roles` en el historial | Eventos WebSocket tras guardar la lectura |
| `app/routers/nodos.py` | `require_roles` en `GET` y `POST /nodos/` | Endpoint `GET /nodos/{id}/prediccion` |
| `app/routers/panel.py` | Dependencia `require_roles` en el router | Usa `calcular_estado` compartido |
| `requirements-dev.txt` | Archivo nuevo con pytest | Archivo nuevo con pytest (**choque de "archivo nuevo en ambas"**: dejar una sola línea de pytest) |
| `requirements.txt` | No lo toca | Nuevas dependencias y conversión a UTF-8 |
| `README.md` | Sección de la Parte B | Sección de la Parte D |

Tras integrar las dos ramas, `POST /lecturas/` exige `X-API-Key` y además emite los eventos WebSocket.

## Pendientes y notas

- Todo se probó con datos simulados. El modelo de predicción hay que reentrenarlo con lecturas reales cuando haya sensores.
- Hoy hay una sola `DEVICE_API_KEY` para todos los dispositivos; más adelante conviene una clave por sensor, para poder revocarla individualmente.
- El modelo entrenado no se sube a Git: cada persona lo genera en su máquina. Mientras no exista, el endpoint usa el respaldo lineal.
- El WebSocket avisa solo cuando entra una lectura por `POST /lecturas/`.
- Las partes A (camiones y rutas) y C (optimizador) se documentan en sus propias ramas.