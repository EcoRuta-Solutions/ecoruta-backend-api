# EcoRuta Backend API

API FastAPI para gestionar nodos, lecturas y usuarios de EcoRuta Trujillo. Usa SQLAlchemy con PostgreSQL/PostGIS y JWT para autenticar usuarios.

## Predicción y tiempo real

### Preparar el entorno

Desde PowerShell, en la carpeta `ecoruta-backend-api`:

```powershell
docker compose up -d db
$env:DATABASE_URL = "postgresql+psycopg2://ecoruta:ecoruta123@localhost:5433/ecoruta_db"
$env:SECRET_KEY = "clave-local-de-pruebas-cambiar"
$env:DEVICE_API_KEY = "clave-local-de-dispositivos"
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe crear_tablas.py
```

Las variables se configuran solo en la sesión actual de PowerShell. No guardes valores reales en la documentación. La URL debe corresponder a la configuración de PostgreSQL de `docker-compose.yml`.

### Generar historial de prueba

En una terminal PowerShell, con las variables anteriores configuradas:

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

En otra terminal, configura `DATABASE_URL` igual que arriba y genera lecturas durante varios minutos:

```powershell
.\venv\Scripts\python.exe -m simulador.simulador
```

Detén el simulador con Ctrl+C. Los datos sintéticos sirven para validar el flujo, no para representar el comportamiento del piloto real.

### Entrenar o actualizar

Con PostgreSQL disponible y `DATABASE_URL` configurada en la terminal:

```powershell
.\venv\Scripts\python.exe -m ml.prediccion.entrenar_modelo
```

El entrenamiento necesita al menos 50 objetivos observables y una división temporal con al menos 30 ejemplos de entrenamiento y 10 de validación. Se excluyen lecturas cuyo cruce del umbral no se observe antes de un vaciado o del fin del historial; el entrenamiento informa el recuento y porcentaje excluidos. Los casos censurados no reciben etiqueta ni se usan para entrenar. También se purgan los ejemplos que cruzan el límite temporal para evitar fuga de información. La línea base lineal y LightGBM se evalúan sobre exactamente las mismas observaciones de validación.

Esta selección de ejemplos es una limitación conocida: el MAE describe solo periodos cuyo próximo cruce quedó observado y no garantiza el mismo error para periodos censurados. Los vaciados se infieren mediante caídas de al menos 20 puntos porcentuales. La línea base usa una tasa mínima de 0.001 puntos porcentuales por hora para poder evaluar también los casos con tasa observada no positiva. La confianza devuelta es una heurística (basada en el MAE relativo para el modelo y en la cantidad de lecturas para la extrapolación lineal), no una probabilidad calibrada. Vuelve a ejecutar el entrenamiento cuando haya más lecturas, incluidos los datos del piloto real; el artefacto regenerable se guarda en `ml/prediccion/modelos/` y se reemplaza al entrenar de nuevo. Si faltan ejemplos válidos, el comando indica cuántos hacen falta y no guarda un modelo nuevo.

Pendiente para la Parte B: validar `X-API-Key` en `POST /lecturas/`. La emisión de eventos WebSocket tras registrar una lectura sí está implementada en esta entrega.

### Consultar una predicción

Abre `http://127.0.0.1:8000/docs`, autentícate con un usuario cuyo rol sea `municipalidad` o `conductor` mediante **Authorize**, y llama a `GET /nodos/{id}/prediccion`. El endpoint devuelve la estimación en horas y fecha, el método (`modelo` o `lineal`) y una confianza entre 0 y 1. Si el nodo no tiene lecturas, está estable o acaba de vaciarse, `horas_estimadas` y `fecha_estimada_critico` serán `null`. El usuario debe tener ya ese rol; el registro público crea ciudadanos.

### Probar el WebSocket

Con el servidor activo, ejecuta en otra terminal:

```powershell
.\venv\Scripts\python.exe scripts/ws_panel_client.py
```

Pega el JWT de un usuario municipal o conductor cuando se solicite. Después envía una lectura desde el simulador o `POST /lecturas/` en `/docs`; el cliente imprimirá eventos `lectura_nueva` y, si cambia la clasificación, `estado_cambiado`. Los estados usan los mismos literales que `/panel/estado`: `normal`, `alerta`, `critico` y `sin_datos`.

## Ejecución del API

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

## Archivos agregados en la Parte Daniel (Predicción y tiempo real)

| Archivo | Qué hace | Quién lo usa o cuándo se ejecuta |
|---|---|---|
| `app/core/connection_manager.py` (nuevo) | Mantiene las conexiones WebSocket activas, distribuye mensajes y elimina clientes cuyo envío falla. | `app/main.py` lo usa para registrar clientes; `app/routers/lecturas.py` lo usa para emitir eventos. |
| `app/core/estado_nodo.py` (nuevo) | Calcula `sin_datos`, `normal`, `alerta` o `critico` según el llenado y el umbral. | Lo usan el router del panel y el endpoint que registra lecturas. |
| `app/schemas/prediccion.py` (nuevo) | Define y valida los campos de la respuesta de predicción, incluidos método y confianza acotada entre 0 y 1. | Lo usa `app/routers/nodos.py` al responder `GET /nodos/{id}/prediccion`. |
| `app/services/prediccion_service.py` (nuevo) | Carga el modelo entrenado con caché y estima las horas al umbral; si no puede usarlo, recurre a la tasa lineal o devuelve una estimación nula en casos sin tasa positiva. | Lo llama el endpoint de predicción por nodo. |
| `ml/prediccion/features.py` (nuevo) | Ordena las lecturas, calcula las features, detecta caídas de al menos 20 puntos y construye etiquetas solo cuando el cruce del umbral queda observado. | Lo comparten el entrenamiento y el servicio para mantener la misma lógica. |
| `ml/prediccion/entrenar_modelo.py` (nuevo) | Lee las lecturas de PostgreSQL, separa datos por tiempo, excluye objetivos censurados, compara LightGBM con la línea base lineal y guarda el modelo. | Se ejecuta manualmente con `python -m ml.prediccion.entrenar_modelo` después de reunir suficientes datos. |
| `scripts/ws_panel_client.py` (nuevo) | Se conecta a `/ws/panel` con un JWT y muestra los mensajes recibidos. | Se ejecuta manualmente para observar eventos; el token puede pedirse por consola o recibirse mediante `ECORUTA_WS_TOKEN`. |
| `tests/test_features_prediccion.py` (nuevo) | Comprueba la detección de vaciados, el reinicio de la tasa y las etiquetas observadas o censuradas. | Lo ejecuta pytest desde la raíz del proyecto. |
| `tests/test_prediccion_service.py` (nuevo) | Comprueba el respaldo lineal y los casos crítico, sin lecturas y tasa cero o negativa. | Lo ejecuta pytest desde la raíz del proyecto, sin base de datos ni red. |
| `requirements-dev.txt` (nuevo) | Fija la versión de pytest para las pruebas de desarrollo, separada de las dependencias de ejecución. | Se instala para ejecutar la suite de pruebas. |
| `app/services/__init__.py`, `ml/__init__.py`, `ml/prediccion/__init__.py` (nuevos) | Marcan los directorios de servicios y predicción como paquetes Python; no agregan lógica de negocio. | Python los usa al importar los módulos de esos paquetes. |
| `app/main.py` (modificado) | Registra `/ws/panel`, valida el JWT y limita la conexión a usuarios activos con rol municipalidad o conductor. | Se carga al iniciar FastAPI y atiende las conexiones WebSocket. |
| `app/routers/nodos.py` (modificado) | Agrega `GET /nodos/{id}/prediccion`, valida el rol y responde 404 si el nodo no existe. | Se ejecuta cuando el cliente consulta la predicción de un nodo. |
| `app/routers/panel.py` (modificado) | Usa el cálculo compartido del estado en lugar de mantener una segunda implementación. | Se ejecuta para las rutas del panel municipal. |
| `app/routers/lecturas.py` (modificado) | Después de guardar una lectura, programa el evento `lectura_nueva` y, si cambió la clasificación, `estado_cambiado`. | Se ejecuta con `POST /lecturas/`; las notificaciones se envían en segundo plano. |
| `.gitignore` (modificado) | Excluye los artefactos de modelo regenerables de `ml/prediccion/modelos/`. | Git lo aplica al revisar cambios y preparar archivos. |
| `requirements.txt` (modificado) | Añade las dependencias de ejecución para LightGBM, features, serialización del modelo y WebSocket. | Se instala al preparar el entorno del backend. |

`requirements.txt` se convirtió de UTF-16 a UTF-8 sin BOM.

### Cómo encajan las piezas

Una lectura llega por `POST /lecturas/`, se guarda en la base de datos, se calcula su estado con la función compartida y se avisa a los clientes conectados a `/ws/panel`. Por otro lado, el entrenamiento genera el modelo que usa el servicio para `GET /nodos/{id}/prediccion`; si no hay un modelo disponible o aplicable, el servicio usa el respaldo lineal.

### Ejecutar las pruebas

Desde la raíz del proyecto, instala pytest y ejecuta la suite:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\venv\Scripts\python.exe -m pytest -q
```

## Integración compartida de esta fase

- `app/main.py`: nueva ruta `@app.websocket("/ws/panel")`.
- `app/routers/nodos.py`: nuevo endpoint `GET /nodos/{id}/prediccion`, protegido para municipalidad y conductor.
- `app/routers/panel.py`: el panel importa `from app.core.estado_nodo import calcular_estado`.
- `app/routers/lecturas.py`: se programan `background_tasks.add_task(connection_manager.broadcast, evento)` y el evento `estado_cambiado` después del commit.
- `.gitignore`: se añadió `ml/prediccion/modelos/` para ignorar el artefacto regenerable.
- `requirements.txt`: nuevas líneas:

```text
joblib==1.5.2
lightgbm==4.6.0
numpy==2.3.3
pandas==2.3.3
scikit-learn==1.7.2
websockets==15.0.1
```
- `requirements-dev.txt`: pytest se mantiene separado de las dependencias de ejecución.
