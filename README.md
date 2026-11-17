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
python scripts\migrar_unificar_flota.py   # base ya existente: agrega columnas nuevas (create_all no las agrega)
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
| GET | `/puntos-criticos/{codigo}/ultimo-reporte` | `municipalidad`, `conductor` | Datos reales |
| POST | `/reportes-campo` | `municipalidad`, `conductor` | Datos reales |
| GET | `/reportes-campo` | `municipalidad`, `conductor` | Datos reales |
| GET | `/reportes-campo/resumen` | `municipalidad`, `conductor` | Datos reales |

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

## Reportes de campo (llenado de puntos críticos)

No existe ningún dato público del nivel de llenado de los puntos críticos. El dato real lo capturan en campo los conductores y la municipalidad, y vive en la tabla `reportes_campo`. **No hay valores supuestos ni lecturas simuladas**: un punto sin reporte vigente se muestra como `sin_datos`.

La tabla la crea `python crear_tablas.py`, que no toca las tablas existentes. Cada reporte guarda:
- el punto, el usuario (sale del token, nunca del cuerpo), el `estado` (`vacio`, `medio`, `lleno` o `desbordado`) y una `observacion` opcional;
- la posición del dispositivo (`lat` y `lon`, opcionales), la `distancia_m` al punto (calculada con PostGIS) y `lejos_del_punto`;
- `foto_url` (reservado para más adelante), `creado_en` y `es_demo`.

Reglas:
- Si el reporte trae `lat`/`lon` y está a más de `REPORTE_DISTANCIA_MAX_M` (150 m por defecto), se marca `lejos_del_punto=true`, **pero se guarda igual**. Sin GPS, `distancia_m` queda null y `lejos_del_punto` en false.
- El estado de un punto es el de su **último** reporte, siempre que tenga menos de `REPORTE_VIGENCIA_HORAS` (24 h por defecto). Si no, el punto queda en `sin_datos`.
- Los dos umbrales se cambian con variables de entorno del mismo nombre; se leen en `app/config.py`.
- Un reporte enviado con una cuenta demo queda con `es_demo=true` y no cuenta como estado real. `GET /reportes-campo?incluir_demo=true` lo muestra para depurar.

Endpoints (roles `municipalidad` y `conductor`):

| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/reportes-campo` | Registra un reporte (201). 404 si el punto no existe; 422 si el estado no es válido o llega `lat` sin `lon`. |
| GET | `/reportes-campo` | Lista paginada, del más reciente al más antiguo: `?punto=<codigo>&desde=&hasta=&limit=&offset=`. |
| GET | `/reportes-campo/resumen` | Puntos por estado según su último reporte vigente, y cuántos están `sin_datos`. |
| GET | `/puntos-criticos/{codigo}/ultimo-reporte` | Último reporte del punto y si sigue vigente; 404 si el punto no existe. |

Además, `GET /puntos-criticos` y `GET /puntos-criticos/{codigo}` traen ahora `ultimo_reporte` (`{estado, creado_en}` o null), `reporte_vigente` y `estado_llenado` (el estado vigente o `sin_datos`).

Ejemplos en PowerShell (con un token de `/auth/login` en `$token`):

```powershell
$h = @{ Authorization = "Bearer $token" }

# Reportar un punto (lat/lon y observacion son opcionales)
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/reportes-campo -Headers $h `
  -ContentType "application/json" `
  -Body '{"codigo_punto": "130101-1", "estado": "lleno", "observacion": "Bolsas en la vereda", "lat": -8.0845, "lon": -79.0456}'

# Últimos reportes de un punto en un rango de fechas
Invoke-RestMethod -Uri "http://127.0.0.1:8000/reportes-campo?punto=130101-1&desde=2026-11-01T00:00:00-05:00&limit=20" -Headers $h

# Resumen para el panel y último reporte de un punto
Invoke-RestMethod -Uri http://127.0.0.1:8000/reportes-campo/resumen -Headers $h
Invoke-RestMethod -Uri http://127.0.0.1:8000/puntos-criticos/130101-1/ultimo-reporte -Headers $h
```

`scripts/limpiar_datos_demo.py` borra los reportes con `es_demo=true` antes que a los usuarios demo. No borra un usuario demo que tenga reportes reales.

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

`seed_demo.py` solo reemplaza lo demo (ver [Datos demo](#datos-demo-seed-y-limpieza)). No toca la flota provisional ni `puntos_criticos`.

`POST /rutas/generar` usa el horario del turno del camión según `app/core/turnos.py` (05:00–13:00, 13:00–21:00 y 21:00–05:00 del día siguiente).

Endpoints:

| Método | Ruta | Quién puede usarlo |
|---|---|---|
| GET | `/flota/resumen` | `municipalidad` |
| GET | `/camiones` | `municipalidad`, `conductor` |
| PATCH | `/camiones/{id}/estado` | `municipalidad` |

- `GET /flota/resumen` da los totales por turno y por estado y cuántos tienen datos provisionales. **Por defecto excluye los camiones con `es_demo=true`.** Para depurar, `?incluir_demo=true` los incluye y `demo` dice cuántos son.
- `GET /camiones` acepta los filtros opcionales `?turno=manana|tarde|noche` y `?estado=operativo|reserva|mantenimiento`. El filtro de turno también encuentra los demo, que se guardan como "Mañana". Sin filtros responde igual que antes, y cada camión trae ahora los campos nuevos.
- `PATCH /camiones/{id}/estado` recibe un cuerpo como `{"estado": "mantenimiento", "activar_reserva": true}`. Con `activar_reserva`, la primera reserva del mismo turno pasa a `operativo`. Si no hay ninguna, responde 409 y no cambia nada. Si el camión no está operativo o el turno no es válido, responde 422.

## Rutas por zona

Son las rutas de recolección por zona de Trujillo (`M-1`, `T-3`, `N-9`…), con su turno, tramo, sectores, horario de recojo y horario para sacar la basura. Viven en la tabla `zonas_ruta`.

**El CSV oficial todavía no está en el repo.** Va en `data/rutas_zona_trujillo.csv` con las columnas `ruta, turno, tramo, sectores, recojo_inicio, recojo_fin, sacar_basura_inicio, sacar_basura_fin` y, opcionalmente, `revisar` (`true`/`false`). Las horas van en formato 24 h (`HH:MM`; `24:00` se guarda como `00:00`). Mientras falte, el importador termina con un error claro y no toca la base.

```powershell
python crear_tablas.py                      # crea zonas_ruta (también la crea el importador)
python scripts\importar_rutas_zona.py
python scripts\importar_rutas_zona.py --archivo otra\ruta.csv
```

- `turno` acepta `manana`, `mañana`, `tarde` o `noche` y se guarda como `manana|tarde|noche`.
- `cruza_medianoche` se calcula: es `true` si el recojo termina después de las 00:00 (por ejemplo 21:00–05:00). Terminar justo a las 24:00 no cuenta.
- `revisar=true` marca datos dudosos. Se activa si el CSV lo pide o si la ruta está en `CODIGOS_REVISAR` del script. Hoy esa lista solo tiene `N-9`, que tiene impreso un hueco 23:00–24:00 y se importa tal cual.
- No se inventan datos: lo que el CSV no trae (tramo, sectores, horario para sacar la basura) queda vacío.
- Actualiza por código de ruta, así que puede correrse varias veces sin duplicar. Al final imprime el total, la cantidad por turno y cuántas rutas están por revisar.

Endpoints (solo lectura, roles `municipalidad` y `conductor`):
- `GET /zonas-ruta`: todas las rutas ordenadas por turno y código. Acepta el filtro opcional `?turno=manana|mañana|tarde|noche` (422 si no es válido). En la respuesta el turno siempre sale como `manana`.
- `GET /zonas-ruta/{codigo}`: detalle (p. ej. `N-9`); 404 si no existe.

## Flota unificada: `camiones` reemplaza a `vehiculos`

La flota vive en una sola tabla, `camiones`. La tabla vieja `vehiculos` ya no se escribe desde la API y se quitará más adelante.

Para preparar una base existente (no borra datos y puede correrse varias veces):

```powershell
python scripts\migrar_unificar_flota.py
python scripts\vincular_conductores_camion.py
```

- `migrar_unificar_flota.py` aplica también `migrar_es_demo.py` y `migrar_camiones_flota.py`. Hace estos cambios:
  - `camiones`: agrega `tipo` y `activo`; `turno` ya admite null.
  - `conductores`: agrega `camion_id` (FK a `camiones`) y `es_demo`.
  - `vehiculos`: agrega `es_demo`; `capacidad_toneladas` admite null y pierde su valor por defecto (el 8 era inventado). Las filas existentes no cambian.
- `vincular_conductores_camion.py` llena `conductores.camion_id` cruzando por placa con `vehiculos`. No pisa un `camion_id` ya asignado. **No crea camiones**: lista las placas de `vehiculos` que no existen en `camiones`, para que se confirmen y se carguen a mano.
- En `camiones`, un valor vacío significa "por confirmar": `tipo`, `turno`, `capacidad_toneladas` y `capacidad`. La capacidad real está pendiente de SEGAT y no se inventa.

Compatibilidad con el panel (sin cambios en el frontend):
- `GET/POST /flota/vehiculos` y `PATCH /flota/vehiculos/{id}` leen y escriben sobre `camiones` y devuelven el mismo esquema (`id, placa, tipo, capacidad_toneladas, estado, activo`), más `turno`. Figuran como **deprecated** en OpenAPI.
  - El `id` es el del camión.
  - `tipo` y `capacidad_toneladas` pueden venir null.
  - `estado` acepta `operativo`, `reserva` o `mantenimiento` (422 con otro valor).
  - Si el POST no trae `turno`, el camión queda con turno null y `/flota/resumen` lo cuenta como sin turno reconocido.
  - Con `capacidad_toneladas` se guarda también `capacidad` en kg (toneladas × 1000).
- `/flota/conductores` valida `camion_id` contra `camiones` (404 si no existe).
  - Sigue aceptando `vehiculo_id` como alias de `camion_id`: es el `id` que devuelve `/flota/vehiculos`. Si llegan los dos con valores distintos, responde 422.
  - En la respuesta, `vehiculo_id` vale lo mismo que `camion_id`.

## Datos demo (seed y limpieza)

Los datos demo llevan `es_demo=true` en `camiones`, `usuarios`, `rutas`, `nodos`, `conductores` y `vehiculos`. Las paradas son demo cuando su ruta lo es. `scripts/migrar_unificar_flota.py` agrega todas esas columnas y marca solo esto:
- usuarios: `conductor@ecoruta.com` y `municipalidad3@ecoruta.com`;
- camiones y vehículos: `TCA-241`, `TCA-508` y `TCA-316`;
- conductores: Luis Rodríguez, María Flores y José Castillo;
- rutas: las de camiones demo;
- nodos: `TRU-001`…`TRU-008`.

`seed_demo.py`:
- No corre si ya hay filas en `zonas_ruta` o `puntos_criticos`, salvo con `python seed_demo.py --force`.
- La flota demo vive solo en `camiones`: ya no crea filas en `vehiculos`. Los conductores demo quedan con `camion_id`.
- Solo borra las rutas demo con sus paradas y las lecturas de los nodos demo. Los camiones, nodos y conductores demo se actualizan en su lugar. Nunca borra rutas ni paradas reales.

`scripts/limpiar_datos_demo.py` borra solo filas con `es_demo=true`: rutas y paradas demo, conductores, camiones, vehículos, nodos (con sus lecturas) y usuarios. Por defecto es un dry-run: ejecuta todo, muestra los números y deshace los cambios.

```powershell
python scripts\limpiar_datos_demo.py            # qué se borraría
python scripts\limpiar_datos_demo.py --aplicar  # borra de verdad
```

- No borra lo demo que todavía usa un dato real. Por ejemplo: un camión demo asignado a un conductor real, un nodo demo en una parada real o un usuario demo vinculado a un conductor real. Lo reporta como bloqueado.
- `conductor@ecoruta.com` se borra cuando se borra su conductor demo (Luis Rodríguez).
- Si falta alguna columna (`es_demo` o `conductores.camion_id`), no borra nada y pide correr `scripts/migrar_unificar_flota.py`.

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