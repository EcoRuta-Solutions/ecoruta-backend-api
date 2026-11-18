"""Endpoints /zonas-ruta con la copia del CSV real (una fila por tramo)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.security import create_access_token
from app.database import get_db
from app.main import app
from app.models.usuario import Usuario
from conftest import importador_zonas
from test_importar_rutas_zona import CSV_REAL

RUTAS = ["/zonas-ruta", "/zonas-ruta/N-9"]
CODIGOS = [f"M-{n}" for n in range(1, 11)] + [f"N-{n}" for n in range(1, 10)]


@pytest.fixture
def entorno(db_limpia):
    importador_zonas.importar(db_limpia, CSV_REAL)

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


def pares(respuesta):
    return [(z["codigo"], z["tramo"]) for z in respuesta.json()]


# --- Permisos -------------------------------------------------------------------------


@pytest.mark.parametrize("ruta", RUTAS)
def test_sin_token_devuelve_401(entorno, ruta):
    cliente, _ = entorno

    assert cliente.get(ruta).status_code == 401


@pytest.mark.parametrize("rol", ["municipalidad", "conductor"])
@pytest.mark.parametrize("ruta", RUTAS)
def test_roles_autorizados_pueden_leer(entorno, rol, ruta):
    cliente, tokens = entorno

    respuesta = cliente.get(ruta, headers={"Authorization": f"Bearer {tokens[rol]}"})

    assert respuesta.status_code == 200


@pytest.mark.parametrize("ruta", RUTAS)
def test_rol_no_autorizado_devuelve_403(entorno, ruta):
    cliente, tokens = entorno

    respuesta = cliente.get(ruta, headers={"Authorization": f"Bearer {tokens['invitado']}"})

    assert respuesta.status_code == 403


# --- Lista: una fila por tramo -----------------------------------------------------------


def test_lista_devuelve_un_elemento_por_tramo_ordenado(cliente):
    respuesta = cliente.get("/zonas-ruta")

    assert respuesta.status_code == 200
    lista = pares(respuesta)
    assert len(lista) == 66
    assert lista[:5] == [("M-1", t) for t in range(1, 6)]
    # Orden por código natural (M-2 antes que M-10) y por tramo dentro de cada ruta.
    assert [c for c in dict.fromkeys(c for c, _ in lista)] == CODIGOS
    assert lista == sorted(lista, key=lambda p: (p[0][0], int(p[0][2:]), p[1]))
    assert all(isinstance(z["tramo"], int) for z in respuesta.json())


@pytest.mark.parametrize(
    ("turno", "rutas", "tramos"),
    [("manana", 10, 36), ("mañana", 10, 36), ("Mañana", 10, 36), ("noche", 9, 30), ("tarde", 0, 0)],
)
def test_filtro_por_turno(cliente, turno, rutas, tramos):
    respuesta = cliente.get("/zonas-ruta", params={"turno": turno})

    assert respuesta.status_code == 200
    lista = pares(respuesta)
    assert len(lista) == tramos
    assert len({c for c, _ in lista}) == rutas
    assert {z["turno"] for z in respuesta.json()} <= {"manana", "noche"}


def test_turno_invalido_devuelve_422(cliente):
    assert cliente.get("/zonas-ruta", params={"turno": "madrugada"}).status_code == 422


# --- Detalle: todos los tramos de una ruta -------------------------------------------------


def test_detalle_devuelve_todos_los_tramos_de_n9(cliente):
    respuesta = cliente.get("/zonas-ruta/n-9")

    assert respuesta.status_code == 200
    tramos = respuesta.json()
    assert [t["tramo"] for t in tramos] == [1, 2, 3, 4]
    assert all(t["codigo"] == "N-9" and t["turno"] == "noche" and t["revisar"] for t in tramos)
    # El hueco impreso: el tramo 1 termina a las 23:00 y el 2 empieza a las 00:00.
    assert (tramos[0]["recojo_fin"], tramos[1]["recojo_inicio"]) == ("23:00:00", "00:00:00")


def test_detalle_con_seis_tramos(cliente):
    tramos = cliente.get("/zonas-ruta/N-3").json()

    assert [t["tramo"] for t in tramos] == [1, 2, 3, 4, 5, 6]
    assert tramos[3]["cruza_medianoche"] is True  # tramo 4: 23:30–00:30


def test_detalle_inexistente_devuelve_404(cliente):
    respuesta = cliente.get("/zonas-ruta/X-99")

    assert respuesta.status_code == 404
    assert respuesta.json()["detail"] == "Zona de ruta no encontrada"


@pytest.mark.parametrize("metodo", ["post", "put", "patch", "delete"])
def test_no_hay_endpoints_de_escritura(cliente, metodo):
    assert getattr(cliente, metodo)("/zonas-ruta/N-9").status_code == 405
