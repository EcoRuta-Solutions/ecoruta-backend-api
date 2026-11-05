# EcoRuta Backend API

API FastAPI para gestionar nodos (contenedores), lecturas de sensores, usuarios, camiones, rutas y predicción de llenado de EcoRuta Trujillo. Usa SQLAlchemy con PostgreSQL/PostGIS (en Docker) y JWT para autenticar a las personas.

## Reparto de partes

| Parte | Tema | Responsable asignado | Rama | Estado |
|---|---|---|---|---|
| B | Roles y protección de endpoints | Anthony Mantilla | `feature/mantilla-reportes` | Implementada y probada |
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

Solo hay dos roles: `municipalidad` y `conductor`. No existe registro público: los usuarios se crean con `python scripts/crear_usuarios_demo.py` (cuentas demo de ambos roles) o directamente en la base, siempre con el rol explícito.

## Roles

El rol `ciudadano` se eliminó: las denuncias ciudadanas las recibe SEGAT por Alerta SEGAT. Con él se retiraron `POST /auth/registro`, los endpoints `/reportes` y la tabla `reportes_ciudadanos`.

Para retirar la tabla y las cuentas demo `ciudadano` de una base existente, saca primero un respaldo y luego:

```powershell
python scripts\eliminar_reportes_ciudadanos.py              # solo muestra lo que haría
python scripts\eliminar_reportes_ciudadanos.py --confirmar  # ejecuta los cambios
```

El script borra la tabla y después solo las cuentas listadas en `CUENTAS_DEMO`; si quedan otros usuarios `ciudadano`, lo avisa para revisarlos a mano.

## Endpoints y protección

| Método | Ruta | Quién puede usarlo | Parte |
|---|---|---|---|
| GET | `/` | Público | Base |
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
| WebSocket | `/ws/panel` | JWT de usuario activo con rol `municipalidad` o `conductor` | D |
| GET | `/puntos-criticos` | `municipalidad`, `conductor` | Datos reales |
| GET | `/puntos-criticos/resumen` | `municipalidad`, `conductor` | Datos reales |
| GET | `/puntos-criticos/{codigo}` | `municipalidad`, `conductor` | Datos reales |

Sin token la respuesta es 401, con un rol no autorizado 403, y con datos inválidos 422.

## Puntos críticos oficiales

Son los 151 puntos críticos de acumulación de residuos del distrito de Trujillo (listado oficial, Tramo III), en `data/puntos_criticos_trujillo.csv`. No son contenedores ni tienen sensor: viven en su propia tabla `puntos_criticos` (geometría `POINT` SRID 4326 con índice GiST) y no se mezclan con `nodos`.

Para importarlos, con la base levantada y el `.env` configurado:

```powershell
python scripts\importar_puntos_criticos.py
python scripts\importar_puntos_criticos.py --archivo otra\ruta.csv  # otro CSV con las mismas columnas
```

El script crea la tabla si falta (también la crea `python crear_tablas.py`), valida cada fila (código, estado, priorización y que lat/lon caigan en Trujillo) y reporta las inválidas sin detenerse. Actualiza por código, así que puede correrse varias veces sin duplicar. Con el archivo oficial debe dar 151 puntos: 110 potenciales, 41 recuperados y 109 con priorización obligatoria.

Endpoints (solo lectura):
- `GET /puntos-criticos`: lista paginada (`limit` de 1 a 200, por defecto 50; `offset`). Filtros opcionales: `estado` (`potencial` o `recuperado`), `prioridad` (`true`/`false`) y `bbox=min_lon,min_lat,max_lon,max_lat`. Responde `{total, limit, offset, items}`; cada punto trae `lat` y `lon` numéricos.
- `GET /puntos-criticos/resumen`: totales por estado y por prioridad.
- `GET /puntos-criticos/{codigo}`: detalle por código (p. ej. `130101-1`); 404 si no existe.

`seed_demo.py` no toca esta tabla: los nodos demo y los puntos críticos conviven.

Las pruebas de puntos críticos usan una base aparte (`<tu_base>_test`, o la de `TEST_DATABASE_URL`), que se crea sola con PostGIS la primera vez; si PostgreSQL no está disponible, esas pruebas se saltan.

## Flota y turnos (SEGAT)

Turnos (`app/core/turnos.py`): `manana` 05:00–13:00, `tarde` 13:00–21:00 y `noche` 21:00–05:00 (cruza la medianoche). El inicio cuenta dentro del turno y el fin no: las 13:00 ya son tarde.

La flota operativa es de 13 camiones en la mañana (más 3 en reserva para reemplazar a uno que falle), 8 en la tarde y 13 en la noche. Cada camión de la tabla `camiones` tiene `turno`, `estado` (`operativo`, `reserva` o `mantenimiento`), `capacidad_toneladas` (puede quedar vacía), `datos_confirmados` y `es_demo`.

**Datos provisionales:** no hay placas reales y la capacidad no está confirmada. Los 37 camiones cargados usan códigos inventados (`CAM-M01`…`CAM-M13`, `CAM-R01`…`CAM-R03`, `CAM-T01`…`CAM-T08`, `CAM-N01`…`CAM-N13`), tienen `datos_confirmados=false` y la capacidad vacía.

Para una base existente, primero se agregan las columnas (no borra datos y puede correrse varias veces) y después se carga la flota:

```powershell
python scripts\migrar_camiones_flota.py
python scripts\cargar_flota_turnos.py
python scripts\cargar_flota_turnos.py --capacidad-toneladas 12.5  # solo cuando haya un dato
```

- `cargar_flota_turnos.py` aplica la migración por su cuenta.
- Si se corre otra vez, no duplica camiones ni cambia los estados que se hayan modificado desde la API.
- Con `--capacidad-toneladas` se guarda además `capacidad` en kg (toneladas × 1000).
- Al terminar, imprime cuántos camiones creó por turno y estado.

`seed_demo.py` necesita la migración. Solo reemplaza sus 3 camiones demo (`es_demo=true`) y las rutas de esos camiones. No toca la flota provisional ni `puntos_criticos`.

Endpoints:

| Método | Ruta | Quién puede usarlo |
|---|---|---|
| GET | `/flota/resumen` | `municipalidad` |
| GET | `/camiones` | `municipalidad`, `conductor` |
| PATCH | `/camiones/{id}/estado` | `municipalidad` |

- `GET /flota/resumen` da los totales por turno y por estado, cuántos son demo y cuántos tienen datos provisionales. Con `?incluir_demo=false` deja fuera los demo.
- `GET /camiones` acepta los filtros opcionales `?turno=manana|tarde|noche` y `?estado=operativo|reserva|mantenimiento`. El filtro de turno también encuentra los demo, que se guardan como "Mañana". Sin filtros responde igual que antes, y cada camión trae ahora los campos nuevos.
- `PATCH /camiones/{id}/estado` recibe un cuerpo como `{"estado": "mantenimiento", "activar_reserva": true}`. Con `activar_reserva`, la primera reserva del mismo turno pasa a `operativo`. Si no hay ninguna, responde 409 y no cambia nada. Si el camión no está operativo o el turno no es válido, responde 422.

---

# Parte B: Roles y protección de endpoints

**Responsable asignado:** Anthony Mantilla · **Rama:** `feature/mantilla-reportes`

Se cerró la protección por rol que faltaba en los endpoints de nodos, lecturas y panel. Esta parte incluía también los reportes ciudadanos, que se retiraron después (ver [Roles](#roles)).

## Archivos agregados o modificados

| Archivo | Estado | Qué hace |
|---|---|---|
| `tests/test_deps.py` | Nuevo | Pruebas con pytest de `require_roles`, sin base de datos. |
| `requirements-dev.txt` | Nuevo | Declara pytest como dependencia de desarrollo, separada de `requirements.txt`. |
| `app/routers/nodos.py` | Modificado | `GET /nodos/` exige municipalidad o conductor; `POST /nodos/` exige municipalidad. |
| `app/routers/lecturas.py` | Modificado | `POST /lecturas/` exige `X-API-Key`; el historial exige municipalidad o conductor. |
| `app/routers/panel.py` | Modificado | Aplica municipalidad/conductor a las tres rutas del panel. |
| `app/schemas/usuario.py` | Modificado | `UsuarioOut.email` pasó de `EmailStr` a `str` para poder responder con cuentas de prueba de dominio `.test`. |
| `simulador/simulador.py` | Modificado | Inicia sesión como municipalidad para registrar nodos y envía `X-API-Key` en cada lectura. |
| `.env.example` | Modificado | Añade `SIMULADOR_EMAIL` y `SIMULADOR_PASSWORD` con valores de ejemplo. |

## Cómo encajan las piezas

Las personas usan sesión Bearer con permisos por rol. Los sensores no inician sesión: envían `X-API-Key`, por lo que **ya no existe el `POST /lecturas/` sin clave**. El simulador se adaptó: obtiene el token municipal desde `/auth/login` para registrar nodos y usa `DEVICE_API_KEY` al enviar lecturas.

## Ejecutar las pruebas

Con el entorno virtual activo:

```powershell
pip install -r requirements-dev.txt
python -m pytest -q
```

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
| `app/main.py` | Incluía el router `reportes` (ya eliminado) | Agrega la ruta `/ws/panel` |
| `app/routers/lecturas.py` | `verify_device_key` en `POST /lecturas/` y `require_roles` en el historial | Eventos WebSocket tras guardar la lectura |
| `app/routers/nodos.py` | `require_roles` en `GET` y `POST /nodos/` | Endpoint `GET /nodos/{id}/prediccion` |
| `app/routers/panel.py` | Dependencia `require_roles` en el router | Usa `calcular_estado` compartido |
| `requirements-dev.txt` | Archivo nuevo con pytest | Archivo nuevo con pytest (dejar una sola línea de pytest) |
| `requirements.txt` | No lo toca | Nuevas dependencias y conversión a UTF-8 |
| `README.md` | Sección de la Parte B | Sección de la Parte D |

Tras integrar las dos ramas, `POST /lecturas/` exige `X-API-Key` y además emite los eventos WebSocket.

## Pendientes y notas

- Todo se probó con datos simulados. El modelo de predicción hay que reentrenarlo con lecturas reales cuando haya sensores.
- Hoy hay una sola `DEVICE_API_KEY` para todos los dispositivos; más adelante conviene una clave por sensor, para poder revocarla individualmente.
- El modelo entrenado no se sube a Git: cada persona lo genera en su máquina. Mientras no exista, el endpoint usa el respaldo lineal.
- El WebSocket avisa solo cuando entra una lectura por `POST /lecturas/`.
- Las partes A (camiones y rutas) y C (optimizador) se documentan en sus propias ramas.