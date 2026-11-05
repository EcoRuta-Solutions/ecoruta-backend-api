import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.security import create_access_token
from app.database import get_db
from app.main import app
from app.models.usuario import Usuario
from conftest import importador

RUTAS = ["/puntos-criticos", "/puntos-criticos/resumen", "/puntos-criticos/130101-1"]


@pytest.fixture
def entorno(db_limpia, csv_prueba):
    importador.importar(db_limpia, csv_prueba)
    Sesion = sessionmaker(bind=db_limpia, autoflush=False)

    tokens = {}
    with Sesion() as db:
        for rol in ("municipalidad", "conductor", "invitado"):
            usuario = Usuario(
                email=f"{rol}@prueba.test", nombre=rol, password_hash="x", rol=rol
            )
            db.add(usuario)
            db.flush()
            tokens[rol] = create_access_token(usuario.id, rol)
        db.commit()

    def get_db_pruebas():
        db = Sesion()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = get_db_pruebas
    try:
        yield TestClient(app), tokens
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def cliente(entorno):
    cliente, tokens = entorno
    cliente.headers["Authorization"] = f"Bearer {tokens['conductor']}"
    return cliente


def codigos(respuesta):
    return [p["codigo"] for p in respuesta.json()["items"]]


# --- Autenticación ---------------------------------------------------------


@pytest.mark.parametrize("ruta", RUTAS)
def test_sin_token_devuelve_401(entorno, ruta):
    cliente, _ = entorno

    assert cliente.get(ruta).status_code == 401


@pytest.mark.parametrize("ruta", RUTAS)
def test_token_invalido_devuelve_401(entorno, ruta):
    cliente, _ = entorno

    respuesta = cliente.get(ruta, headers={"Authorization": "Bearer no-es-un-jwt"})

    assert respuesta.status_code == 401


@pytest.mark.parametrize("rol", ["municipalidad", "conductor"])
@pytest.mark.parametrize("ruta", RUTAS)
def test_roles_autorizados_pueden_leer(entorno, rol, ruta):
    cliente, tokens = entorno

    respuesta = cliente.get(ruta, headers={"Authorization": f"Bearer {tokens[rol]}"})

    assert respuesta.status_code == 200


def test_rol_no_autorizado_devuelve_403(entorno):
    cliente, tokens = entorno

    respuesta = cliente.get(
        "/puntos-criticos", headers={"Authorization": f"Bearer {tokens['invitado']}"}
    )

    assert respuesta.status_code == 403


@pytest.mark.parametrize("metodo", ["post", "put", "patch", "delete"])
def test_no_hay_endpoints_de_escritura(cliente, metodo):
    respuesta = getattr(cliente, metodo)("/puntos-criticos/130101-1")

    assert respuesta.status_code == 405


# --- Lista ------------------------------------------------------------------


def test_lista_devuelve_lat_lon_numericos(cliente):
    respuesta = cliente.get("/puntos-criticos")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert (cuerpo["total"], cuerpo["limit"], cuerpo["offset"]) == (4, 50, 0)
    primero = cuerpo["items"][0]
    assert primero["codigo"] == "130101-1"
    assert isinstance(primero["lat"], float) and isinstance(primero["lon"], float)
    assert primero["lat"] == pytest.approx(-8.084408)
    assert primero["lon"] == pytest.approx(-79.045583)
    assert "ubicacion" not in primero


@pytest.mark.parametrize(
    ("parametros", "esperados"),
    [
        ({"estado": "potencial"}, ["130101-1", "130101-3"]),
        ({"estado": "recuperado"}, ["130101-2", "130101-4"]),
        ({"prioridad": "true"}, ["130101-1", "130101-3"]),
        ({"prioridad": "false"}, ["130101-2", "130101-4"]),
        ({"bbox": "-79.03,-8.12,-79.01,-8.09"}, ["130101-3", "130101-4"]),
        ({"bbox": "-79.03,-8.12,-79.01,-8.09", "estado": "potencial"}, ["130101-3"]),
        ({"bbox": "-79.00,-8.12,-78.99,-8.09"}, []),
    ],
)
def test_lista_filtra(cliente, parametros, esperados):
    respuesta = cliente.get("/puntos-criticos", params=parametros)

    assert respuesta.status_code == 200
    assert codigos(respuesta) == esperados
    assert respuesta.json()["total"] == len(esperados)


def test_lista_pagina_con_limit_y_offset(cliente):
    respuesta = cliente.get("/puntos-criticos", params={"limit": 2, "offset": 2})

    assert respuesta.json()["total"] == 4
    assert codigos(respuesta) == ["130101-3", "130101-4"]


@pytest.mark.parametrize(
    "parametros",
    [
        {"limit": 201},
        {"limit": 0},
        {"offset": -1},
        {"estado": "eliminado"},
        {"bbox": "-79.03,-8.12,-79.01"},
        {"bbox": "a,b,c,d"},
        {"bbox": "-79.01,-8.12,-79.03,-8.09"},  # min_lon > max_lon
    ],
)
def test_lista_rechaza_parametros_invalidos(cliente, parametros):
    assert cliente.get("/puntos-criticos", params=parametros).status_code == 422


# --- Detalle y resumen ------------------------------------------------------


def test_detalle_devuelve_el_punto(cliente):
    respuesta = cliente.get("/puntos-criticos/130101-4")

    assert respuesta.status_code == 200
    punto = respuesta.json()
    assert punto["codigo"] == "130101-4"
    assert punto["estado"] == "recuperado"
    assert punto["priorizacion_obligatoria"] is False
    assert punto["direccion"] == "Jirón Pucará con la calle Los Amautas."
    assert punto["referencia"] is None
    assert (punto["este_utm17s"], punto["norte_utm17s"]) == (717883, 9105033)
    assert punto["lat"] == pytest.approx(-8.09172)
    assert punto["lon"] == pytest.approx(-79.022761)


def test_detalle_inexistente_devuelve_404(cliente):
    respuesta = cliente.get("/puntos-criticos/130101-999")

    assert respuesta.status_code == 404
    assert respuesta.json()["detail"] == "Punto crítico no encontrado"


def test_resumen_cuenta_por_estado_y_prioridad(cliente):
    respuesta = cliente.get("/puntos-criticos/resumen")

    assert respuesta.json() == {
        "total": 4,
        "por_estado": {"potencial": 2, "recuperado": 2},
        "por_prioridad": {"prioritarios": 2, "no_prioritarios": 2},
    }
