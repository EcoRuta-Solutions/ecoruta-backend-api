"""/flota/vehiculos y /flota/conductores sobre `camiones`, con el esquema de siempre."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core.security import create_access_token
from app.database import get_db
from app.main import app
from app.models.camion import Camion
from app.models.conductor import Conductor
from app.models.usuario import Usuario
from app.models.vehiculo import Vehiculo
from conftest import carga_flota

CAMPOS_VEHICULO = {"id", "placa", "tipo", "capacidad_toneladas", "estado", "activo", "turno"}


@pytest.fixture
def entorno(db_limpia):
    carga_flota.cargar(db_limpia)  # 37 camiones provisionales, sin capacidad
    Sesion = sessionmaker(bind=db_limpia, autoflush=False)
    tokens = {}
    with Sesion() as db:
        for rol in ("municipalidad", "conductor"):
            usuario = Usuario(email=f"{rol}@prueba.test", nombre=rol, password_hash="x", rol=rol)
            db.add(usuario)
            db.flush()
            tokens[rol] = create_access_token(usuario.id, rol)
        # Fila vieja en `vehiculos`: ya no se lista.
        db.add(Vehiculo(placa="VIE-001", tipo="Compactador", capacidad_toneladas=8))
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
        yield cliente, Sesion, tokens
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def cliente(entorno):
    return entorno[0]


def id_camion(Sesion, placa):
    with Sesion() as db:
        return db.query(Camion).filter(Camion.placa == placa).one().id


# --- /flota/vehiculos ------------------------------------------------------------


def test_listar_devuelve_camiones_con_el_mismo_esquema(cliente):
    respuesta = cliente.get("/flota/vehiculos")

    assert respuesta.status_code == 200
    vehiculos = respuesta.json()
    assert len(vehiculos) == 37
    assert all(set(v) == CAMPOS_VEHICULO for v in vehiculos)
    primero = vehiculos[0]
    assert primero["placa"] == "CAM-M01"
    assert primero["capacidad_toneladas"] is None  # por confirmar, no se inventa
    assert primero["tipo"] is None
    assert (primero["estado"], primero["activo"], primero["turno"]) == ("operativo", True, "manana")
    assert "VIE-001" not in {v["placa"] for v in vehiculos}


def test_solo_municipalidad(entorno):
    cliente, _, tokens = entorno

    respuesta = cliente.get(
        "/flota/vehiculos", headers={"Authorization": f"Bearer {tokens['conductor']}"}
    )

    assert respuesta.status_code == 403


def test_endpoints_de_vehiculos_marcados_deprecated():
    rutas = app.openapi()["paths"]
    assert rutas["/flota/vehiculos"]["get"]["deprecated"] is True
    assert rutas["/flota/vehiculos"]["post"]["deprecated"] is True
    assert rutas["/flota/vehiculos/{vehiculo_id}"]["patch"]["deprecated"] is True
    assert "deprecated" not in rutas["/flota/conductores"]["get"]


def test_crear_sin_turno_ni_capacidad_no_inventa_nada(entorno):
    cliente, Sesion, _ = entorno

    respuesta = cliente.post("/flota/vehiculos", json={"placa": "ABC-123"})

    assert respuesta.status_code == 201
    creado = respuesta.json()
    assert set(creado) == CAMPOS_VEHICULO
    assert creado["capacidad_toneladas"] is None
    assert creado["tipo"] is None
    assert creado["turno"] is None
    with Sesion() as db:
        camion = db.get(Camion, creado["id"])
        assert (camion.capacidad, camion.datos_confirmados, camion.es_demo) == (None, False, False)
        assert db.query(Vehiculo).count() == 1  # no escribe en la tabla vieja

    resumen = cliente.get("/flota/resumen").json()
    assert resumen["total"] == 38
    assert resumen["sin_turno_reconocido"] == 1
    # /camiones sigue respondiendo con el camión sin turno.
    camiones = cliente.get("/camiones").json()
    assert next(c for c in camiones if c["placa"] == "ABC-123")["turno"] is None


def test_crear_con_turno_y_capacidad(entorno):
    cliente, Sesion, _ = entorno

    respuesta = cliente.post(
        "/flota/vehiculos",
        json={"placa": "ABC-124", "tipo": "Volquete", "capacidad_toneladas": 12.5, "turno": "Mañana"},
    )

    assert respuesta.status_code == 201
    assert respuesta.json()["turno"] == "manana"
    with Sesion() as db:
        camion = db.get(Camion, respuesta.json()["id"])
        assert (camion.capacidad_toneladas, camion.capacidad) == (12.5, 12500)


@pytest.mark.parametrize(
    ("cuerpo", "codigo"),
    [
        ({"placa": "CAM-M01"}, 409),
        ({"placa": "ABC-125", "estado": "roto"}, 422),
        ({"placa": "ABC-125", "turno": "madrugada"}, 422),
        ({"placa": "ABC-125", "capacidad_toneladas": 0}, 422),
        ({"placa": "CORTA"}, 422),
    ],
)
def test_crear_rechaza(cliente, cuerpo, codigo):
    assert cliente.post("/flota/vehiculos", json=cuerpo).status_code == codigo


def test_actualizar_escribe_en_camiones(entorno):
    cliente, Sesion, _ = entorno
    camion_id = id_camion(Sesion, "CAM-T01")

    respuesta = cliente.patch(
        f"/flota/vehiculos/{camion_id}",
        json={"estado": "mantenimiento", "capacidad_toneladas": 10, "tipo": "Compactador", "activo": False},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "mantenimiento"
    with Sesion() as db:
        camion = db.get(Camion, camion_id)
        assert (camion.estado, camion.capacidad, camion.tipo, camion.activo) == (
            "mantenimiento", 10000, "Compactador", False,
        )
        assert camion.turno == "tarde"  # lo no enviado no cambia


def test_actualizar_capacidad_a_null(entorno):
    cliente, Sesion, _ = entorno
    camion_id = id_camion(Sesion, "CAM-T02")
    cliente.patch(f"/flota/vehiculos/{camion_id}", json={"capacidad_toneladas": 9})

    cliente.patch(f"/flota/vehiculos/{camion_id}", json={"capacidad_toneladas": None})

    with Sesion() as db:
        camion = db.get(Camion, camion_id)
        assert (camion.capacidad_toneladas, camion.capacidad) == (None, None)


@pytest.mark.parametrize(
    ("cuerpo", "codigo"),
    [
        ({"placa": "CAM-M02"}, 409),
        ({"placa": None}, 422),
        ({"estado": None}, 422),
        ({"estado": "roto"}, 422),
    ],
)
def test_actualizar_rechaza(entorno, cuerpo, codigo):
    cliente, Sesion, _ = entorno
    camion_id = id_camion(Sesion, "CAM-M01")

    assert cliente.patch(f"/flota/vehiculos/{camion_id}", json=cuerpo).status_code == codigo


def test_actualizar_inexistente_404(cliente):
    assert cliente.patch("/flota/vehiculos/99999", json={"tipo": "x"}).status_code == 404


# --- /flota/conductores ----------------------------------------------------------


def test_crear_conductor_con_vehiculo_id_lo_toma_como_camion(entorno):
    cliente, Sesion, _ = entorno
    vehiculo = cliente.get("/flota/vehiculos").json()[0]  # lo que hace el panel

    respuesta = cliente.post(
        "/flota/conductores", json={"nombre": "Ana", "vehiculo_id": vehiculo["id"]}
    )

    assert respuesta.status_code == 201
    creado = respuesta.json()
    assert creado["camion_id"] == creado["vehiculo_id"] == vehiculo["id"]
    with Sesion() as db:
        guardado = db.get(Conductor, creado["id"])
        assert guardado.camion_id == vehiculo["id"]
        assert guardado.vehiculo_id is None  # la columna vieja no se escribe


def test_crear_conductor_con_camion_id(entorno):
    cliente, Sesion, _ = entorno
    camion_id = id_camion(Sesion, "CAM-N01")

    respuesta = cliente.post("/flota/conductores", json={"nombre": "Beto", "camion_id": camion_id})

    assert respuesta.status_code == 201
    assert respuesta.json()["vehiculo_id"] == camion_id


@pytest.mark.parametrize(
    ("cuerpo", "codigo"),
    [
        ({"nombre": "X", "camion_id": 99999}, 404),
        ({"nombre": "X", "vehiculo_id": 99999}, 404),
        ({"nombre": "X", "camion_id": 1, "vehiculo_id": 2}, 422),
    ],
)
def test_crear_conductor_valida_camion(cliente, cuerpo, codigo):
    respuesta = cliente.post("/flota/conductores", json=cuerpo)

    assert respuesta.status_code == codigo
    if codigo == 404:
        assert respuesta.json()["detail"] == "Camión no encontrado"


def test_actualizar_conductor_cambia_y_quita_camion(entorno):
    cliente, Sesion, _ = entorno
    uno, otro = id_camion(Sesion, "CAM-M01"), id_camion(Sesion, "CAM-M02")
    creado = cliente.post("/flota/conductores", json={"nombre": "Ceci", "camion_id": uno}).json()

    cambiado = cliente.patch(f"/flota/conductores/{creado['id']}", json={"vehiculo_id": otro})
    assert cambiado.json()["camion_id"] == otro

    solo_nombre = cliente.patch(f"/flota/conductores/{creado['id']}", json={"nombre": "Cecilia"})
    assert solo_nombre.json()["camion_id"] == otro  # no enviar camion no lo quita

    quitado = cliente.patch(f"/flota/conductores/{creado['id']}", json={"camion_id": None})
    assert quitado.json()["camion_id"] is None
    assert quitado.json()["vehiculo_id"] is None

    assert cliente.patch(
        f"/flota/conductores/{creado['id']}", json={"camion_id": 99999}
    ).status_code == 404


def test_listar_conductores_expone_camion_como_vehiculo_id(entorno):
    cliente, Sesion, _ = entorno
    camion_id = id_camion(Sesion, "CAM-T03")
    with Sesion() as db:
        viejo = db.query(Vehiculo).one()
        db.add(Conductor(nombre="Legado", vehiculo_id=viejo.id, camion_id=camion_id))
        db.commit()

    conductor = cliente.get("/flota/conductores").json()[0]

    assert (conductor["camion_id"], conductor["vehiculo_id"]) == (camion_id, camion_id)

