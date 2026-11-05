import pytest
from conftest import carga_flota as carga
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.security import create_access_token
from app.database import get_db
from app.main import app
from app.models.camion import Camion
from app.models.usuario import Usuario

# Igual que CAMIONES en seed_demo.py.
CAMIONES_DEMO = [("TCA-241", "Mañana"), ("TCA-508", "Tarde"), ("TCA-316", "Noche")]


def conteos(engine):
    Sesion = sessionmaker(bind=engine)
    with Sesion() as db:
        filas = db.query(Camion.turno, Camion.estado, Camion.es_demo).all()
    return sorted(filas)


@pytest.fixture
def entorno(db_limpia):
    Sesion = sessionmaker(bind=db_limpia, autoflush=False)

    tokens = {}
    with Sesion() as db:
        for placa, turno in CAMIONES_DEMO:
            db.add(Camion(placa=placa, capacidad=8000, turno=turno, es_demo=True))
        for rol in ("municipalidad", "conductor", "invitado"):
            usuario = Usuario(
                email=f"{rol}@prueba.test", nombre=rol, password_hash="x", rol=rol
            )
            db.add(usuario)
            db.flush()
            tokens[rol] = create_access_token(usuario.id, rol)
        db.commit()

    carga.cargar(db_limpia)

    def get_db_pruebas():
        db = Sesion()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = get_db_pruebas
    try:
        yield TestClient(app), tokens, Sesion
    finally:
        app.dependency_overrides.pop(get_db, None)


def con_token(tokens, rol):
    return {"Authorization": f"Bearer {tokens[rol]}"}


def id_de(Sesion, placa):
    with Sesion() as db:
        return db.query(Camion.id).filter(Camion.placa == placa).scalar()


# --- Carga inicial ---------------------------------------------------------


def test_carga_crea_37_provisionales_por_turno_y_estado(db_limpia):
    resultado = carga.cargar(db_limpia)

    assert resultado.total_creados == 37
    assert resultado.creados == {
        ("manana", "operativo"): 13,
        ("manana", "reserva"): 3,
        ("tarde", "operativo"): 8,
        ("noche", "operativo"): 13,
    }
    Sesion = sessionmaker(bind=db_limpia)
    with Sesion() as db:
        camiones = db.query(Camion).all()
    assert all(c.datos_confirmados is False for c in camiones)
    assert all(c.es_demo is False for c in camiones)
    assert all(c.capacidad is None and c.capacidad_toneladas is None for c in camiones)
    assert {c.placa for c in camiones} >= {"CAM-M01", "CAM-M13", "CAM-R03", "CAM-T08", "CAM-N13"}


def test_carga_es_idempotente(db_limpia):
    carga.cargar(db_limpia)
    antes = conteos(db_limpia)

    segunda = carga.cargar(db_limpia)

    assert segunda.total_creados == 0
    assert segunda.ya_existian == 37
    assert conteos(db_limpia) == antes
    assert len(antes) == 37


def test_carga_no_borra_demo_ni_pisa_estados_cambiados(entorno):
    _, _, Sesion = entorno
    with Sesion() as db:
        camion = db.query(Camion).filter(Camion.placa == "CAM-N01").one()
        camion.estado = "mantenimiento"
        db.commit()

    carga.cargar(Sesion.kw["bind"])

    with Sesion() as db:
        assert db.query(Camion).filter(Camion.es_demo.is_(True)).count() == 3
        assert db.query(Camion).count() == 40
        assert db.query(Camion.estado).filter(Camion.placa == "CAM-N01").scalar() == "mantenimiento"


def test_carga_con_capacidad_calcula_kilogramos(db_limpia):
    carga.cargar(db_limpia)
    resultado = carga.cargar(db_limpia, capacidad_toneladas=12.5)

    assert resultado.capacidad_actualizada == 37
    Sesion = sessionmaker(bind=db_limpia)
    with Sesion() as db:
        camion = db.query(Camion).filter(Camion.placa == "CAM-T01").one()
    assert camion.capacidad_toneladas == 12.5
    assert camion.capacidad == 12500
    assert camion.datos_confirmados is False


def test_carga_rechaza_capacidad_no_positiva(db_limpia):
    with pytest.raises(ValueError):
        carga.cargar(db_limpia, capacidad_toneladas=0)


# --- Autorización ----------------------------------------------------------


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [
        ("get", "/flota/resumen"),
        ("get", "/camiones"),
        ("patch", "/camiones/1/estado"),
    ],
)
def test_sin_token_devuelve_401(entorno, metodo, ruta):
    cliente, _, _ = entorno
    respuesta = getattr(cliente, metodo)(ruta, **({"json": {"estado": "mantenimiento"}} if metodo == "patch" else {}))
    assert respuesta.status_code == 401


@pytest.mark.parametrize(
    ("rol", "metodo", "ruta"),
    [
        ("conductor", "get", "/flota/resumen"),
        ("invitado", "get", "/flota/resumen"),
        ("invitado", "get", "/camiones"),
        ("conductor", "patch", "/camiones/1/estado"),
        ("invitado", "patch", "/camiones/1/estado"),
    ],
)
def test_rol_no_permitido_devuelve_403(entorno, rol, metodo, ruta):
    cliente, tokens, _ = entorno
    extra = {"json": {"estado": "mantenimiento"}} if metodo == "patch" else {}
    respuesta = getattr(cliente, metodo)(ruta, headers=con_token(tokens, rol), **extra)
    assert respuesta.status_code == 403


# --- Resumen ---------------------------------------------------------------


def test_resumen_por_turno_y_estado(entorno):
    cliente, tokens, _ = entorno

    datos = cliente.get("/flota/resumen", headers=con_token(tokens, "municipalidad")).json()

    assert datos["total"] == 40
    assert datos["demo"] == 3
    assert datos["datos_provisionales"] == 40
    assert datos["por_turno"]["manana"] == {
        "operativo": 14, "reserva": 3, "mantenimiento": 0, "total": 17
    }
    assert datos["por_turno"]["tarde"]["operativo"] == 9
    assert datos["por_turno"]["noche"]["operativo"] == 14
    assert datos["por_estado"] == {
        "operativo": 37, "reserva": 3, "mantenimiento": 0, "total": 40
    }


def test_resumen_sin_demo(entorno):
    cliente, tokens, _ = entorno

    datos = cliente.get(
        "/flota/resumen",
        params={"incluir_demo": "false"},
        headers=con_token(tokens, "municipalidad"),
    ).json()

    assert datos["total"] == 37
    assert datos["demo"] == 0
    assert datos["por_turno"]["manana"]["operativo"] == 13


# --- Listado con filtros ---------------------------------------------------


def test_listado_sin_filtros_devuelve_todos_con_los_campos_de_siempre(entorno):
    cliente, tokens, _ = entorno

    respuesta = cliente.get("/camiones", headers=con_token(tokens, "conductor"))

    assert respuesta.status_code == 200
    camiones = respuesta.json()
    assert len(camiones) == 40
    demo = next(c for c in camiones if c["placa"] == "TCA-241")
    assert demo["capacidad"] == 8000
    assert demo["turno"] == "Mañana"
    assert demo["es_demo"] is True
    assert demo["estado"] == "operativo"


def test_filtro_por_turno_incluye_demo_con_formato_antiguo(entorno):
    cliente, tokens, _ = entorno

    camiones = cliente.get(
        "/camiones", params={"turno": "manana"}, headers=con_token(tokens, "municipalidad")
    ).json()

    placas = {c["placa"] for c in camiones}
    assert len(camiones) == 17
    assert "TCA-241" in placas
    assert {"CAM-M01", "CAM-R01"} <= placas


def test_filtro_por_turno_y_estado(entorno):
    cliente, tokens, _ = entorno

    camiones = cliente.get(
        "/camiones",
        params={"turno": "manana", "estado": "reserva"},
        headers=con_token(tokens, "municipalidad"),
    ).json()

    assert sorted(c["placa"] for c in camiones) == ["CAM-R01", "CAM-R02", "CAM-R03"]


def test_filtro_por_estado_sin_resultados(entorno):
    cliente, tokens, _ = entorno

    camiones = cliente.get(
        "/camiones", params={"estado": "mantenimiento"}, headers=con_token(tokens, "municipalidad")
    ).json()

    assert camiones == []


@pytest.mark.parametrize("params", [{"turno": "madrugada"}, {"estado": "roto"}])
def test_filtro_invalido_devuelve_422(entorno, params):
    cliente, tokens, _ = entorno

    respuesta = cliente.get("/camiones", params=params, headers=con_token(tokens, "municipalidad"))

    assert respuesta.status_code == 422


# --- Cambio de estado ------------------------------------------------------


def test_mantenimiento_activando_reserva_del_mismo_turno(entorno):
    cliente, tokens, Sesion = entorno
    camion_id = id_de(Sesion, "CAM-M05")

    respuesta = cliente.patch(
        f"/camiones/{camion_id}/estado",
        json={"estado": "mantenimiento", "activar_reserva": True},
        headers=con_token(tokens, "municipalidad"),
    )

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["camion"]["placa"] == "CAM-M05"
    assert datos["camion"]["estado"] == "mantenimiento"
    assert datos["reserva_activada"]["placa"] == "CAM-R01"
    assert datos["reserva_activada"]["estado"] == "operativo"

    resumen = cliente.get("/flota/resumen", headers=con_token(tokens, "municipalidad")).json()
    assert resumen["por_turno"]["manana"] == {
        "operativo": 14, "reserva": 2, "mantenimiento": 1, "total": 17
    }


def test_activar_reserva_sin_reservas_en_el_turno_devuelve_409(entorno):
    cliente, tokens, Sesion = entorno
    camion_id = id_de(Sesion, "CAM-N01")

    respuesta = cliente.patch(
        f"/camiones/{camion_id}/estado",
        json={"estado": "mantenimiento", "activar_reserva": True},
        headers=con_token(tokens, "municipalidad"),
    )

    assert respuesta.status_code == 409
    assert "reserva" in respuesta.json()["detail"]
    assert "noche" in respuesta.json()["detail"]
    with Sesion() as db:
        assert db.query(Camion.estado).filter(Camion.id == camion_id).scalar() == "operativo"


def test_reservas_se_agotan(entorno):
    cliente, tokens, Sesion = entorno
    cabeceras = con_token(tokens, "municipalidad")
    cuerpo = {"estado": "mantenimiento", "activar_reserva": True}

    for placa in ("CAM-M01", "CAM-M02", "CAM-M03"):
        respuesta = cliente.patch(f"/camiones/{id_de(Sesion, placa)}/estado", json=cuerpo, headers=cabeceras)
        assert respuesta.status_code == 200

    cuarta = cliente.patch(f"/camiones/{id_de(Sesion, 'CAM-M04')}/estado", json=cuerpo, headers=cabeceras)

    assert cuarta.status_code == 409
    with Sesion() as db:
        assert db.query(Camion.estado).filter(Camion.placa == "CAM-M04").scalar() == "operativo"


def test_cambio_simple_sin_reserva(entorno):
    cliente, tokens, Sesion = entorno
    camion_id = id_de(Sesion, "CAM-T02")
    cabeceras = con_token(tokens, "municipalidad")

    ida = cliente.patch(f"/camiones/{camion_id}/estado", json={"estado": "mantenimiento"}, headers=cabeceras)
    vuelta = cliente.patch(f"/camiones/{camion_id}/estado", json={"estado": "operativo"}, headers=cabeceras)

    assert ida.status_code == 200
    assert ida.json()["reserva_activada"] is None
    assert vuelta.json()["camion"]["estado"] == "operativo"


def test_activar_reserva_desde_camion_no_operativo_devuelve_422(entorno):
    cliente, tokens, Sesion = entorno
    camion_id = id_de(Sesion, "CAM-R01")

    respuesta = cliente.patch(
        f"/camiones/{camion_id}/estado",
        json={"estado": "mantenimiento", "activar_reserva": True},
        headers=con_token(tokens, "municipalidad"),
    )

    assert respuesta.status_code == 422
    with Sesion() as db:
        assert db.query(Camion).filter(Camion.estado == "reserva").count() == 3


def test_estado_invalido_y_camion_inexistente(entorno):
    cliente, tokens, Sesion = entorno
    cabeceras = con_token(tokens, "municipalidad")

    invalido = cliente.patch(
        f"/camiones/{id_de(Sesion, 'CAM-M01')}/estado", json={"estado": "roto"}, headers=cabeceras
    )
    inexistente = cliente.patch("/camiones/99999/estado", json={"estado": "mantenimiento"}, headers=cabeceras)

    assert invalido.status_code == 422
    assert inexistente.status_code == 404
