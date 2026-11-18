"""Contenedor prototipo con sensor: punto PROTO-UTP, ingesta, vigencia, alertas y ruta del conductor.

Las coordenadas del prototipo en estas pruebas son de prueba (dentro de Trujillo);
el script real exige las del lugar donde esté el contenedor.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import config
from app.core import deps
from app.core.security import create_access_token
from app.database import get_db
from app.main import app
from app.models.alerta import Alerta
from app.models.camion import Camion
from app.models.conductor import Conductor
from app.models.lectura import Lectura
from app.models.nodo import Nodo
from app.models.punto_critico import PuntoCritico
from app.models.reporte_campo import ReporteCampo
from app.models.ruta import Parada, Ruta
from app.models.usuario import Usuario
from app.services import distancias_service as ds
from app.services import reportes_service
from conftest import importador, prototipo, simulador_sensor

CLAVE_DISPOSITIVO = "clave-de-dispositivo-de-prueba"
LAT_PROTO, LON_PROTO = -8.1105, -79.0275  # solo para pruebas


@pytest.fixture
def entorno(db_limpia, csv_prueba, tmp_path, monkeypatch):
    importador.importar(db_limpia, csv_prueba)  # 4 puntos oficiales
    prototipo.crear(db_limpia, LAT_PROTO, LON_PROTO)
    monkeypatch.setattr(deps, "DEVICE_API_KEY", CLAVE_DISPOSITIVO)
    monkeypatch.setattr(config, "OPTIMIZADOR_TIEMPO_MAX_S", 1)
    monkeypatch.setattr(config, "MATRIZ_DISTANCIAS_ARCHIVO", str(tmp_path / "sin_matriz.json"))

    Sesion = sessionmaker(bind=db_limpia, autoflush=False)
    ids, tokens = {}, {}
    with Sesion() as db:
        for placa in ("CAM-M01", "CAM-M02"):
            camion = Camion(placa=placa, turno="manana", estado="operativo")
            db.add(camion)
            db.flush()
            ids[placa] = camion.id
        for nombre, rol in [("muni", "municipalidad"), ("cond", "conductor"),
                            ("otro", "conductor"), ("sin_camion", "conductor"), ("invitado", "invitado")]:
            usuario = Usuario(email=f"{nombre}@prueba.test", nombre=nombre, password_hash="x", rol=rol)
            db.add(usuario)
            db.flush()
            ids[nombre] = usuario.id
            tokens[nombre] = create_access_token(usuario.id, rol)
        db.add(Conductor(nombre="Cond", usuario_id=ids["cond"], camion_id=ids["CAM-M01"]))
        db.add(Conductor(nombre="Otro", usuario_id=ids["otro"], camion_id=ids["CAM-M02"]))
        db.add(Conductor(nombre="Sin camión", usuario_id=ids["sin_camion"]))
        db.commit()

    def get_db_pruebas():
        with Sesion() as db:
            yield db

    app.dependency_overrides[get_db] = get_db_pruebas
    try:
        yield TestClient(app), Sesion, ids, tokens
    finally:
        app.dependency_overrides.pop(get_db, None)


def cabecera(tokens, quien):
    return {"Authorization": f"Bearer {tokens[quien]}"}


def leer(cliente, nivel, codigo="PROTO-UTP", clave=CLAVE_DISPOSITIVO):
    return cliente.post(
        "/sensores/lecturas", json={"codigo": codigo, "nivel_pct": nivel}, headers={"X-API-Key": clave}
    )


def reporte_campo(Sesion, codigo, estado, usuario_id, horas_atras=1):
    with Sesion() as db:
        punto = db.query(PuntoCritico).filter(PuntoCritico.codigo_unico == codigo).one()
        db.add(ReporteCampo(punto_critico_id=punto.id, usuario_id=usuario_id, estado=estado,
                            creado_en=datetime.now(timezone.utc) - timedelta(hours=horas_atras)))
        db.commit()


# --- A. Punto prototipo ------------------------------------------------------------------------


def test_crear_prototipo_es_idempotente_y_vincula_el_sensor(entorno, db_limpia):
    _, Sesion, *_ = entorno

    segundo = prototipo.crear(db_limpia, LAT_PROTO + 0.001, LON_PROTO)

    assert (segundo.punto_creado, segundo.nodo_creado) == (False, False)
    with Sesion() as db:
        [punto] = db.query(PuntoCritico).filter(PuntoCritico.es_prototipo.is_(True)).all()
        assert (punto.codigo_unico, punto.direccion) == ("PROTO-UTP", "Prototipo EcoRuta (UTP)")
        assert punto.lat == pytest.approx(LAT_PROTO + 0.001)
        nodo = db.get(Nodo, punto.nodo_id)
        assert (nodo.codigo, nodo.es_demo) == ("PROTO-UTP", False)
        assert db.query(Nodo).filter(Nodo.codigo == "PROTO-UTP").count() == 1


@pytest.mark.parametrize(("lat", "lon"), [(-95, -79.0), (-8.1, 200)])
def test_crear_prototipo_rechaza_coordenadas_invalidas(lat, lon):
    with pytest.raises(prototipo.CoordenadaInvalida):
        prototipo.validar(lat, lon)


def test_crear_prototipo_exige_lat_y_lon(monkeypatch):
    monkeypatch.setattr("sys.argv", ["crear_punto_prototipo.py", "--lat", "-8.1"])
    with pytest.raises(SystemExit):
        prototipo.main()


def test_prototipo_fuera_del_listado_oficial_y_sus_estadisticas(entorno):
    cliente, _, _, tokens = entorno
    h = cabecera(tokens, "muni")

    oficial = cliente.get("/puntos-criticos", headers=h).json()
    mapa = cliente.get("/puntos-criticos", params={"incluir_prototipo": "true"}, headers=h).json()

    assert oficial["total"] == 4
    assert "PROTO-UTP" not in [p["codigo"] for p in oficial["items"]]
    assert mapa["total"] == 5
    proto = next(p for p in mapa["items"] if p["codigo"] == "PROTO-UTP")
    assert proto["es_prototipo"] is True and proto["estado_llenado"] == "sin_datos"
    assert cliente.get("/puntos-criticos/resumen", headers=h).json()["total"] == 4
    assert cliente.get("/reportes-campo/resumen", headers=h).json()["total_puntos"] == 4
    assert cliente.get("/puntos-criticos/PROTO-UTP", headers=h).status_code == 200


# --- B. Ingesta y mapeo ---------------------------------------------------------------------


def test_ingesta_con_clave_valida(entorno):
    cliente, Sesion, *_ = entorno

    respuesta = leer(cliente, 42.5)

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert (cuerpo["codigo"], cuerpo["punto_codigo"], cuerpo["estado_llenado"]) == ("PROTO-UTP", "PROTO-UTP", "medio")
    assert cuerpo["alerta_creada"] is None
    with Sesion() as db:
        lectura = db.query(Lectura).one()
        assert lectura.fill_pct == 42.5
        reporte = db.query(ReporteCampo).one()
        assert (reporte.origen, reporte.usuario_id, reporte.es_demo, reporte.nivel_pct) == ("sensor", None, False, 42.5)


@pytest.mark.parametrize("clave", [None, "", "clave-equivocada"])
def test_ingesta_sin_clave_o_con_clave_invalida_da_401(entorno, clave):
    cliente, Sesion, *_ = entorno
    headers = {} if clave is None else {"X-API-Key": clave}

    respuesta = cliente.post("/sensores/lecturas", json={"codigo": "PROTO-UTP", "nivel_pct": 50}, headers=headers)

    assert respuesta.status_code == 401
    with Sesion() as db:
        assert db.query(Lectura).count() == 0


@pytest.mark.parametrize("nivel", [-1, 120.1, "mucho"])
def test_ingesta_rechaza_nivel_fuera_de_rango(entorno, nivel):
    cliente, *_ = entorno

    assert leer(cliente, nivel).status_code == 422


def test_ingesta_de_nodo_inexistente_da_404(entorno):
    cliente, *_ = entorno

    assert leer(cliente, 50, codigo="NO-EXISTE").status_code == 404


@pytest.mark.parametrize(
    ("nivel", "estado"),
    [(0, "vacio"), (34.9, "vacio"), (35, "medio"), (84.9, "medio"), (85, "lleno"),
     (99.9, "lleno"), (100, "desbordado"), (120, "desbordado")],
)
def test_mapeo_de_nivel_a_estado(nivel, estado):
    assert reportes_service.estado_por_nivel(nivel).value == estado


def test_umbrales_configurables(monkeypatch):
    monkeypatch.setattr(config, "SENSOR_NIVEL_LLENO", 70)

    assert reportes_service.estado_por_nivel(72).value == "lleno"


def test_lectura_actualiza_el_punto_en_el_mapa(entorno):
    cliente, _, _, tokens = entorno
    leer(cliente, 91)

    punto = cliente.get("/puntos-criticos/PROTO-UTP", headers=cabecera(tokens, "cond")).json()

    assert punto["estado_llenado"] == "lleno"
    assert punto["reporte_vigente"] is True
    assert (punto["ultimo_reporte"]["origen"], punto["ultimo_reporte"]["nivel_pct"]) == ("sensor", 91)


# --- Vigencia de 15 minutos -----------------------------------------------------------------


@pytest.mark.parametrize(("minutos", "esperado"), [(14, "lleno"), (16, "sin_datos")])
def test_vigencia_de_15_minutos_del_sensor(entorno, minutos, esperado):
    cliente, Sesion, _, tokens = entorno
    with Sesion() as db:
        punto = db.query(PuntoCritico).filter(PuntoCritico.codigo_unico == "PROTO-UTP").one()
        db.add(ReporteCampo(punto_critico_id=punto.id, origen="sensor", nivel_pct=90, estado="lleno",
                            creado_en=datetime.now(timezone.utc) - timedelta(minutes=minutos)))
        db.commit()

    punto = cliente.get("/puntos-criticos/PROTO-UTP", headers=cabecera(tokens, "muni")).json()

    assert punto["estado_llenado"] == esperado


def test_reporte_de_campo_sigue_valiendo_24_horas(entorno):
    cliente, Sesion, ids, tokens = entorno
    reporte_campo(Sesion, "130101-1", "lleno", ids["cond"], horas_atras=5)

    punto = cliente.get("/puntos-criticos/130101-1", headers=cabecera(tokens, "muni")).json()

    assert punto["estado_llenado"] == "lleno"


# --- C. Alertas -------------------------------------------------------------------------------


def test_alerta_una_sola_vez_por_transicion(entorno):
    cliente, Sesion, _, tokens = entorno
    creadas = [leer(cliente, nivel).json()["alerta_creada"] for nivel in (50, 88, 95, 104, 90)]

    assert [a is not None for a in creadas] == [False, True, False, False, False]
    assert creadas[1]["mensaje"] == "Contenedor lleno: PROTO-UTP (88%)"
    activas = cliente.get("/alertas/activas", headers=cabecera(tokens, "muni")).json()
    assert [a["mensaje"] for a in activas] == ["Contenedor lleno: PROTO-UTP (88%)"]
    assert activas[0]["punto_codigo"] == "PROTO-UTP" and isinstance(activas[0]["lat"], float)

    bajo = leer(cliente, 60).json()  # baja de 85: se resuelve
    assert bajo["alertas_resueltas"] == 1
    assert cliente.get("/alertas/activas", headers=cabecera(tokens, "cond")).json() == []

    otra = leer(cliente, 86).json()  # nuevo episodio: nueva alerta
    assert otra["alerta_creada"]["mensaje"] == "Contenedor lleno: PROTO-UTP (86%)"
    with Sesion() as db:
        alertas = db.query(Alerta).order_by(Alerta.id).all()
        assert [(a.activa, a.motivo_resolucion) for a in alertas] == [(False, "nivel_bajo"), (True, None)]


def test_alerta_se_resuelve_al_recolectar_el_punto(entorno):
    cliente, Sesion, ids, tokens = entorno
    leer(cliente, 97)
    ruta = cliente.post("/rutas/generar-mia", headers=cabecera(tokens, "cond")).json()["ruta"]
    detalle = cliente.get(f"/rutas/{ruta['ruta_id']}", headers=cabecera(tokens, "cond")).json()
    parada = next(p for p in detalle["paradas"] if p["punto_critico"]["codigo"] == "PROTO-UTP")

    respuesta = cliente.patch(
        f"/rutas/{ruta['ruta_id']}/paradas/{parada['id']}", json={"recolectado": True},
        headers=cabecera(tokens, "cond"),
    )

    assert respuesta.status_code == 200
    assert cliente.get("/alertas/activas", headers=cabecera(tokens, "muni")).json() == []
    with Sesion() as db:
        assert db.query(Alerta).one().motivo_resolucion == "recolectado"


def test_alertas_activas_roles(entorno):
    cliente, _, _, tokens = entorno

    assert cliente.get("/alertas/activas").status_code == 401
    assert cliente.get("/alertas/activas", headers=cabecera(tokens, "invitado")).status_code == 403
    for quien in ("muni", "cond"):
        assert cliente.get("/alertas/activas", headers=cabecera(tokens, quien)).status_code == 200


# --- D. Ruta del conductor --------------------------------------------------------------------


def test_ruta_del_conductor_solo_con_puntos_llenos(entorno):
    cliente, Sesion, ids, tokens = entorno
    leer(cliente, 92)  # PROTO-UTP lleno (sensor)
    reporte_campo(Sesion, "130101-1", "desbordado", ids["muni"])
    reporte_campo(Sesion, "130101-2", "medio", ids["muni"])  # no entra
    reporte_campo(Sesion, "130101-3", "lleno", ids["muni"], horas_atras=30)  # vencido: no entra
    with Sesion() as db:  # ruta de otro camión: no debe aparecer
        db.add(Ruta(fecha_inicio=date.today(), fecha_fin=date.today(), hora_inicio=datetime.now(),
                    hora_fin=datetime.now(), camion_id=ids["CAM-M02"], conductor_id=ids["otro"],
                    estado="Pendiente"))
        db.commit()

    respuesta = cliente.post("/rutas/generar-mia", headers=cabecera(tokens, "cond"))

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    ruta = cuerpo["ruta"]
    assert ruta["camion"]["placa"] == "CAM-M01"
    assert ruta["conductor_id"] == ids["cond"]  # usuarios.id
    assert sorted(p["codigo"] for p in ruta["paradas"]) == ["130101-1", "PROTO-UTP"]
    assert cuerpo["nro_puntos"] == 2
    assert cuerpo["metodo_distancia"] == "haversine_aprox"

    mias = cliente.get("/rutas/mias", headers=cabecera(tokens, "cond")).json()
    assert [r["id"] for r in mias] == [ruta["ruta_id"]]
    assert all(r["camion"]["placa"] == "CAM-M01" for r in mias)


def test_ruta_del_conductor_sin_tope_de_paradas(entorno):
    cliente, Sesion, ids, tokens = entorno
    for codigo in ("130101-1", "130101-2", "130101-3", "130101-4"):
        reporte_campo(Sesion, codigo, "lleno", ids["muni"])
    leer(cliente, 99)

    ruta = cliente.post("/rutas/generar-mia", headers=cabecera(tokens, "cond")).json()["ruta"]

    assert len(ruta["paradas"]) == 5  # todos en un solo camión


def test_ruta_del_conductor_sin_puntos_llenos_da_422(entorno):
    cliente, _, _, tokens = entorno
    leer(cliente, 40)

    respuesta = cliente.post("/rutas/generar-mia", headers=cabecera(tokens, "cond"))

    assert respuesta.status_code == 422
    assert "No hay puntos llenos" in respuesta.json()["detail"]


def test_ruta_del_conductor_con_ruta_en_proceso_da_409(entorno):
    cliente, Sesion, ids, tokens = entorno
    leer(cliente, 90)
    primera = cliente.post("/rutas/generar-mia", headers=cabecera(tokens, "cond")).json()["ruta"]
    with Sesion() as db:
        db.get(Ruta, primera["ruta_id"]).estado = "en_proceso"
        db.commit()

    respuesta = cliente.post("/rutas/generar-mia", headers=cabecera(tokens, "cond"))

    assert respuesta.status_code == 409
    assert "ruta en proceso" in respuesta.json()["detail"]


def test_ruta_del_conductor_reemplaza_la_pendiente(entorno):
    cliente, Sesion, _, tokens = entorno
    leer(cliente, 90)
    primera = cliente.post("/rutas/generar-mia", headers=cabecera(tokens, "cond")).json()

    segunda = cliente.post("/rutas/generar-mia", headers=cabecera(tokens, "cond")).json()

    assert segunda["rutas_reemplazadas"] == 1
    with Sesion() as db:
        assert db.get(Ruta, primera["ruta"]["ruta_id"]) is None
        assert db.query(Ruta).count() == 1
        assert db.query(Parada).count() == 1


def test_conductor_sin_camion_da_409_y_municipalidad_no_puede(entorno):
    cliente, _, _, tokens = entorno
    leer(cliente, 90)

    sin_camion = cliente.post("/rutas/generar-mia", headers=cabecera(tokens, "sin_camion"))
    muni = cliente.post("/rutas/generar-mia", headers=cabecera(tokens, "muni"))

    assert sin_camion.status_code == 409 and "camión asignado" in sin_camion.json()["detail"]
    assert muni.status_code == 403


def test_reparto_por_turno_no_incluye_el_prototipo(entorno):
    cliente, Sesion, ids, tokens = entorno
    leer(cliente, 95)
    reporte_campo(Sesion, "130101-1", "lleno", ids["muni"])

    datos = cliente.post(
        "/rutas/generar", json={"turno": "manana", "solo_con_reporte_lleno": True},
        headers=cabecera(tokens, "muni"),
    ).json()

    codigos = [p["codigo"] for r in datos["rutas"] for p in r["paradas"]]
    assert codigos == ["130101-1"]


# --- Matriz mixta -----------------------------------------------------------------------------


def test_matriz_mixta_usa_osrm_donde_puede():
    puntos = [ds.Punto("A", -8.10, -79.03), ds.Punto("B", -8.11, -79.02), ds.Punto("PROTO", -8.105, -79.025)]
    cache = {
        "codigos": ["A", "B"],
        "coordenadas": {p.codigo: ds.clave_coordenada(p.lat, p.lon) for p in puntos[:2]},
        "distancias_m": [[0, 1500], [1600, 0]],
    }

    estricta = ds.matriz_para_puntos(puntos, cache=cache)
    mixta = ds.matriz_para_puntos(puntos, cache=cache, permitir_mixta=True)

    assert estricta.metodo == "haversine_aprox"
    assert mixta.metodo == "osrm_parcial"
    assert (mixta.km[0][1], mixta.km[1][0]) == (1.5, 1.6)
    assert mixta.km[0][2] == pytest.approx(ds.matriz_haversine(puntos)[0][2])


# --- F. Simulador ----------------------------------------------------------------------------


def test_simulador_rampa_de_niveles():
    assert simulador_sensor.niveles(10, 100, 10) == [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    assert simulador_sensor.niveles(10, 95, 30) == [10, 40, 70, 95]
    assert simulador_sensor.niveles(100, 40, 30) == [100, 70, 40]
    with pytest.raises(ValueError):
        simulador_sensor.niveles(10, 130, 10)


def test_simulador_envia_con_la_clave_del_entorno_sin_imprimirla(monkeypatch, capsys):
    enviados = []
    monkeypatch.setenv("DEVICE_API_KEY", CLAVE_DISPOSITIVO)

    def enviar(url, clave, codigo, nivel, timeout=10):
        enviados.append((url, clave, codigo, nivel))
        estado = reportes_service.estado_por_nivel(nivel).value
        return 201, {"estado_llenado": estado, "alerta_creada": {"mensaje": "x"} if nivel == 90 else None}

    monkeypatch.setattr(simulador_sensor, "enviar", enviar)

    codigo = simulador_sensor.main(
        ["--url", "http://api.prueba", "--desde", "70", "--hasta", "90", "--paso", "10", "--intervalo", "0"],
        dormir=lambda s: None,
    )

    assert codigo == 0
    assert [(c, n) for _, _, c, n in enviados] == [("PROTO-UTP", 70), ("PROTO-UTP", 80), ("PROTO-UTP", 90)]
    assert all(clave == CLAVE_DISPOSITIVO for _, clave, _, _ in enviados)
    salida = capsys.readouterr().out
    assert CLAVE_DISPOSITIVO not in salida
    assert "ALERTA" in salida


# --- Migración -----------------------------------------------------------------------------


def test_migracion_sensor_es_idempotente_desde_el_esquema_anterior(db_limpia):
    from sqlalchemy import inspect, text

    from conftest import _cargar_script

    migracion = _cargar_script("migrar_sensor_prototipo")
    with db_limpia.begin() as c:
        c.execute(text("DROP TABLE alertas"))
        c.execute(text("ALTER TABLE puntos_criticos DROP COLUMN es_prototipo, DROP COLUMN nodo_id"))
        c.execute(text("ALTER TABLE reportes_campo DROP COLUMN origen, DROP COLUMN nivel_pct"))
        c.execute(text("ALTER TABLE reportes_campo ALTER COLUMN usuario_id SET NOT NULL"))

    migracion.migrar(db_limpia)
    migracion.migrar(db_limpia)

    inspector = inspect(db_limpia)
    puntos = {c["name"] for c in inspector.get_columns("puntos_criticos")}
    reportes = {c["name"]: c for c in inspector.get_columns("reportes_campo")}
    assert {"es_prototipo", "nodo_id"} <= puntos
    assert {"origen", "nivel_pct"} <= reportes.keys()
    assert reportes["usuario_id"]["nullable"] is True
    checks = [c["name"] for c in inspector.get_check_constraints("reportes_campo")]
    assert checks.count("ck_reportes_campo_origen") == 1
    assert checks.count("ck_reportes_campo_usuario_si_campo") == 1
    assert inspector.has_table("alertas")
