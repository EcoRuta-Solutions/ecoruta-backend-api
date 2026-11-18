"""POST /rutas/generar: rutas por turno con puntos críticos y flota reales.

Los puntos, camiones y reportes de estas pruebas se crean solo para ejercitar
el generador (coordenadas dentro de Trujillo); no son datos oficiales.
"""

import json
import math
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import config
from app.core.security import create_access_token
from app.database import get_db
from app.main import app
from app.models.camion import Camion
from app.models.conductor import Conductor
from app.models.punto_critico import PuntoCritico
from app.models.reporte_campo import ReporteCampo
from app.models.ruta import Parada, Ruta
from app.models.usuario import Usuario
from conftest import importador

FECHA = date(2026, 11, 20)

# 10 puntos de prueba en una grilla dentro del rango de Trujillo.
FILAS_PUNTOS = [
    [f"130101-{n}", "Potencial", "SI" if n <= 4 else "NO",
     f"{-8.120 + (n % 5) * 0.006:.6f}", f"{-79.050 + (n // 5) * 0.008:.6f}",
     "", "", f"Calle de prueba {n}", ""]
    for n in range(1, 11)
]

# placa, turno, estado, es_demo
CAMIONES = [
    ("CAM-M01", "manana", "operativo", False),
    ("CAM-M02", "manana", "operativo", False),
    ("CAM-M03", "Mañana", "operativo", False),  # formato viejo del turno
    ("CAM-R01", "manana", "reserva", False),
    ("CAM-X01", "manana", "mantenimiento", False),
    ("TCA-241", "Mañana", "operativo", True),  # demo: nunca entra
    ("CAM-N01", "noche", "operativo", False),
    ("CAM-N02", "noche", "operativo", False),
]


@pytest.fixture
def entorno(db_limpia, escribir_csv, tmp_path, monkeypatch):
    importador.importar(db_limpia, escribir_csv(FILAS_PUNTOS))
    monkeypatch.setattr(config, "OPTIMIZADOR_TIEMPO_MAX_S", 1)
    # Sin matriz OSRM salvo que la prueba la escriba aquí.
    monkeypatch.setattr(config, "MATRIZ_DISTANCIAS_ARCHIVO", str(tmp_path / "matriz.json"))

    Sesion = sessionmaker(bind=db_limpia, autoflush=False)
    tokens, ids = {}, {}
    with Sesion() as db:
        for placa, turno, estado, demo in CAMIONES:
            db.add(Camion(placa=placa, turno=turno, estado=estado, es_demo=demo))
        for rol in ("municipalidad", "conductor"):
            usuario = Usuario(email=f"{rol}@prueba.test", nombre=rol, password_hash="x", rol=rol)
            db.add(usuario)
            db.flush()
            tokens[rol] = create_access_token(usuario.id, rol)
            ids[rol] = usuario.id
        db.commit()

    def get_db_pruebas():
        db = Sesion()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = get_db_pruebas
    cliente = TestClient(app)
    cliente.headers["Authorization"] = f"Bearer {tokens['municipalidad']}"
    try:
        yield cliente, Sesion, tokens, ids, tmp_path
    finally:
        app.dependency_overrides.pop(get_db, None)


def generar(cliente, **cuerpo):
    return cliente.post("/rutas/generar", json={"turno": "manana", "fecha": FECHA.isoformat(), **cuerpo})


def codigos_de(respuesta):
    return [p["codigo"] for r in respuesta["rutas"] for p in r["paradas"]]


# --- Reparto ------------------------------------------------------------------------


def test_reparto_equilibrado_por_paradas(entorno):
    cliente, Sesion, *_ = entorno

    respuesta = generar(cliente)

    assert respuesta.status_code == 201
    datos = respuesta.json()
    assert (datos["turno"], datos["nro_camiones"], datos["nro_puntos"]) == ("manana", 3, 10)
    assert datos["max_paradas_por_ruta"] == math.ceil(10 / 3) == 4
    tamanos = [len(r["paradas"]) for r in datos["rutas"]]
    assert sum(tamanos) == 10 and max(tamanos) <= 4
    assert sorted(codigos_de(datos)) == sorted(f[0] for f in FILAS_PUNTOS)  # cada punto una vez
    placas = {r["camion"]["placa"] for r in datos["rutas"]}
    assert placas <= {"CAM-M01", "CAM-M02", "CAM-M03"}  # sin reserva, mantenimiento ni demo
    assert datos["distancia_total_km"] == pytest.approx(sum(r["distancia_km"] for r in datos["rutas"]), abs=0.01)
    assert datos["parametros"]["capacidad_camion_usada"] is False
    for ruta in datos["rutas"]:
        assert [p["orden"] for p in ruta["paradas"]] == list(range(1, len(ruta["paradas"]) + 1))
        assert {"codigo", "lat", "lon", "direccion", "punto_critico_id"} <= ruta["paradas"][0].keys()
        esperado = ruta["distancia_km"] / 20 * 60 + len(ruta["paradas"]) * 5
        assert ruta["tiempo_estimado_min"] == pytest.approx(esperado, abs=0.2)

    with Sesion() as db:
        rutas = db.query(Ruta).all()
        assert len(rutas) == len(datos["rutas"])
        assert all(r.es_demo is False and r.turno == "manana" and r.estado == "Pendiente" for r in rutas)
        assert all(r.hora_inicio == datetime(2026, 11, 20, 5) for r in rutas)
        paradas = db.query(Parada).all()
        assert len(paradas) == 10
        assert all(p.punto_critico_id is not None and p.nodo_id is None for p in paradas)


def test_incluir_reserva_suma_camiones(entorno):
    cliente, *_ = entorno

    datos = generar(cliente, incluir_reserva=True).json()

    assert datos["nro_camiones"] == 4
    assert datos["max_paradas_por_ruta"] == 3
    assert all(len(r["paradas"]) <= 3 for r in datos["rutas"])


def test_max_paradas_por_ruta_menor_al_minimo_da_422(entorno):
    cliente, *_ = entorno

    respuesta = generar(cliente, max_paradas_por_ruta=3)  # 10 puntos / 3 camiones necesita 4

    assert respuesta.status_code == 422
    assert "al menos 4" in respuesta.json()["detail"]


def test_solo_prioritarios(entorno):
    cliente, *_ = entorno

    datos = generar(cliente, solo_prioritarios=True).json()

    assert datos["nro_puntos"] == 4
    assert sorted(codigos_de(datos)) == ["130101-1", "130101-2", "130101-3", "130101-4"]


def test_solo_con_reporte_lleno_usa_reportes_vigentes(entorno):
    cliente, Sesion, _, ids, _ = entorno
    ahora = datetime.now(timezone.utc)
    with Sesion() as db:
        punto = {p.codigo_unico: p.id for p in db.query(PuntoCritico)}
        for codigo, estado, horas in [
            ("130101-1", "lleno", 1), ("130101-2", "desbordado", 2),
            ("130101-3", "lleno", 30),  # vencido
            ("130101-4", "medio", 1),
        ]:
            db.add(ReporteCampo(punto_critico_id=punto[codigo], usuario_id=ids["conductor"],
                                estado=estado, creado_en=ahora - timedelta(hours=horas)))
        db.commit()

    datos = generar(cliente, solo_con_reporte_lleno=True).json()

    assert sorted(codigos_de(datos)) == ["130101-1", "130101-2"]


def test_sin_puntos_con_los_filtros_da_404(entorno):
    cliente, *_ = entorno

    respuesta = generar(cliente, solo_con_reporte_lleno=True)

    assert respuesta.status_code == 404


# --- Sin camiones ---------------------------------------------------------------------


def test_turno_sin_camiones_da_409_y_no_crea_nada(entorno):
    cliente, Sesion, *_ = entorno

    respuesta = generar(cliente, turno="tarde")

    assert respuesta.status_code == 409
    assert "No hay camiones operativos" in respuesta.json()["detail"]
    assert "tarde" in respuesta.json()["detail"]
    with Sesion() as db:
        assert db.query(Ruta).count() == 0


# --- Método de distancia --------------------------------------------------------------


def test_sin_matriz_usa_haversine_aprox(entorno):
    cliente, *_ = entorno

    datos = generar(cliente).json()

    assert datos["metodo_distancia"] == "haversine_aprox"
    assert datos["parametros"]["factor_circuito"] == 1.3
    assert "factor_circuito" in datos["parametros"]["provisionales"]


def escribir_matriz(ruta, Sesion, metros=1000, cambiar_coordenada=False):
    with Sesion() as db:
        puntos = [(p.codigo_unico, p.lat, p.lon) for p in db.query(PuntoCritico).order_by(PuntoCritico.id)]
    coordenadas = {c: [round(lat, 6), round(lon, 6)] for c, lat, lon in puntos}
    if cambiar_coordenada:
        coordenadas["130101-1"][0] += 0.001
    n = len(puntos)
    datos = {
        "fuente": "osrm",
        "codigos": [c for c, _, _ in puntos],
        "coordenadas": coordenadas,
        "distancias_m": [[0 if i == j else metros for j in range(n)] for i in range(n)],
    }
    ruta.write_text(json.dumps(datos), encoding="utf-8")


def test_con_matriz_usa_osrm(entorno):
    cliente, Sesion, _, _, tmp_path = entorno
    escribir_matriz(tmp_path / "matriz.json", Sesion, metros=1000)

    datos = generar(cliente).json()

    assert datos["metodo_distancia"] == "osrm"
    assert datos["parametros"]["factor_circuito"] is None
    # Todas las distancias valen 1 km: cada ruta de k paradas mide k-1 km.
    for ruta in datos["rutas"]:
        assert ruta["distancia_km"] == pytest.approx(len(ruta["paradas"]) - 1)


def test_matriz_desactualizada_vuelve_a_haversine(entorno):
    cliente, Sesion, _, _, tmp_path = entorno
    escribir_matriz(tmp_path / "matriz.json", Sesion, cambiar_coordenada=True)

    assert generar(cliente).json()["metodo_distancia"] == "haversine_aprox"


# --- Regeneración ----------------------------------------------------------------------


def test_regenerar_reemplaza_pendientes(entorno):
    cliente, Sesion, *_ = entorno

    primera = generar(cliente).json()
    segunda = generar(cliente).json()

    assert segunda["rutas_reemplazadas"] == len(primera["rutas"])
    assert len(segunda["rutas"]) == len(primera["rutas"])
    with Sesion() as db:
        assert db.query(Ruta).count() == len(segunda["rutas"])
        assert db.query(Parada).count() == 10
        assert {r.id for r in db.query(Ruta)} == {r["ruta_id"] for r in segunda["rutas"]}


def test_regenerar_no_toca_rutas_en_curso_ni_completadas_ni_otros_turnos(entorno):
    cliente, Sesion, *_ = entorno
    primera = generar(cliente).json()
    generar(cliente, turno="noche")
    en_curso, completada = primera["rutas"][0], primera["rutas"][1]
    with Sesion() as db:
        db.get(Ruta, en_curso["ruta_id"]).estado = "en_proceso"
        db.get(Ruta, completada["ruta_id"]).estado = "Completado"
        db.commit()

    nueva = generar(cliente).json()

    ocupados = {en_curso["camion"]["placa"], completada["camion"]["placa"]}
    assert sorted(nueva["camiones_con_ruta_en_curso"]) == sorted(ocupados)
    assert nueva["nro_camiones"] == 1
    assert {r["camion"]["placa"] for r in nueva["rutas"]}.isdisjoint(ocupados)
    ya_asignados = {p["codigo"] for r in (en_curso, completada) for p in r["paradas"]}
    assert set(codigos_de(nueva)).isdisjoint(ya_asignados)
    assert nueva["nro_puntos"] == 10 - len(ya_asignados)
    with Sesion() as db:
        assert db.get(Ruta, en_curso["ruta_id"]).estado == "en_proceso"
        assert len(db.get(Ruta, completada["ruta_id"]).paradas) == len(completada["paradas"])
        assert db.query(Ruta).filter(Ruta.turno == "noche").count() >= 1


def test_todos_los_camiones_ocupados_da_409(entorno):
    cliente, Sesion, *_ = entorno
    generar(cliente, turno="noche")
    with Sesion() as db:
        for ruta in db.query(Ruta).filter(Ruta.turno == "noche"):
            ruta.estado = "en_proceso"
        db.commit()

    respuesta = generar(cliente, turno="noche")

    assert respuesta.status_code == 409
    assert "ya tienen una ruta en curso" in respuesta.json()["detail"]


def test_no_reemplaza_rutas_creadas_a_mano(entorno):
    cliente, Sesion, *_ = entorno
    with Sesion() as db:
        camion = db.query(Camion).filter(Camion.placa == "CAM-M01").one()
        db.add(Ruta(fecha_inicio=FECHA, fecha_fin=FECHA, hora_inicio=datetime(2026, 11, 20, 5),
                    hora_fin=datetime(2026, 11, 20, 13), camion_id=camion.id, estado="Pendiente"))
        db.commit()

    generar(cliente)
    generar(cliente)

    with Sesion() as db:
        assert db.query(Ruta).filter(Ruta.turno.is_(None)).count() == 1


# --- Noche -----------------------------------------------------------------------------


def test_noche_empieza_21_y_cruza_medianoche(entorno, monkeypatch):
    cliente, *_ = entorno
    monkeypatch.setattr(config, "OPTIMIZADOR_MINUTOS_POR_PARADA", 60)  # 5 paradas ≈ 5 h

    datos = generar(cliente, turno="noche").json()

    assert datos["nro_camiones"] == 2
    for ruta in datos["rutas"]:
        inicio = datetime.fromisoformat(ruta["hora_inicio"])
        fin = datetime.fromisoformat(ruta["hora_fin"])
        assert inicio == datetime(2026, 11, 20, 21)
        assert fin.date() == date(2026, 11, 21)  # termina al día siguiente
        assert ruta["excede_turno"] is (fin > datetime(2026, 11, 21, 5))


def test_ruta_que_pasa_el_fin_del_turno_se_marca(entorno, monkeypatch):
    cliente, *_ = entorno
    monkeypatch.setattr(config, "OPTIMIZADOR_MINUTOS_POR_PARADA", 200)

    datos = generar(cliente, turno="noche").json()

    assert all(r["excede_turno"] for r in datos["rutas"])


# --- Contrato y permisos ---------------------------------------------------------------


@pytest.mark.parametrize("cuerpo", [{"turno": "madrugada"}, {}, {"turno": "manana", "max_paradas_por_ruta": 0}])
def test_peticion_invalida_da_422(entorno, cuerpo):
    cliente, *_ = entorno

    assert cliente.post("/rutas/generar", json=cuerpo).status_code == 422


def test_solo_municipalidad_genera(entorno):
    cliente, _, tokens, _, _ = entorno

    respuesta = cliente.post(
        "/rutas/generar", json={"turno": "manana"},
        headers={"Authorization": f"Bearer {tokens['conductor']}"},
    )

    assert respuesta.status_code == 403


def test_mi_ruta_del_conductor_con_puntos_criticos(entorno):
    cliente, Sesion, tokens, ids, _ = entorno
    with Sesion() as db:
        camion = db.query(Camion).filter(Camion.placa == "CAM-N01").one()
        db.add(Conductor(nombre="Conductor real", usuario_id=ids["conductor"], camion_id=camion.id))
        db.commit()

    generada = generar(cliente, turno="noche").json()
    suya = next(r for r in generada["rutas"] if r["camion"]["placa"] == "CAM-N01")
    otra = next(r for r in generada["rutas"] if r["camion"]["placa"] == "CAM-N02")
    assert suya["conductor_id"] == ids["conductor"]
    assert otra["conductor_id"] is None  # sin conductor asignado: no se inventa

    mias = cliente.get(
        "/rutas/mias", headers={"Authorization": f"Bearer {tokens['conductor']}"}
    ).json()

    assert [r["id"] for r in mias] == [suya["ruta_id"]]
    ruta = mias[0]
    assert (ruta["turno"], ruta["metodo_distancia"]) == ("noche", "haversine_aprox")
    assert ruta["distancia_km"] == suya["distancia_km"]
    parada = sorted(ruta["paradas"], key=lambda p: p["orden"])[0]
    assert parada["nodo_id"] is None and parada["nodo"] is None
    assert parada["punto_critico"]["codigo"] == suya["paradas"][0]["codigo"]
    assert parada["punto_critico"]["estado_llenado"] == "sin_datos"
    assert isinstance(parada["punto_critico"]["lat"], float)

    detalle = cliente.get(f"/rutas/{suya['ruta_id']}").json()
    assert len(detalle["paradas"]) == len(suya["paradas"])
