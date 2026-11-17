"""Endpoints /zonas-ruta (con filas de PRUEBA, no datos oficiales)."""

import csv

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.security import create_access_token
from app.database import get_db
from app.main import app
from app.models.usuario import Usuario
from conftest import importador_zonas
from test_importar_rutas_zona import CABECERA, FILAS_PRUEBA

RUTAS = ["/zonas-ruta", "/zonas-ruta/N-9"]


@pytest.fixture
def entorno(db_limpia, tmp_path):
    archivo = tmp_path / "zonas.csv"
    with open(archivo, "w", encoding="utf-8", newline="") as salida:
        escritor = csv.writer(salida)
        escritor.writerow(CABECERA)
        escritor.writerows(FILAS_PRUEBA)
    importador_zonas.importar(db_limpia, archivo)

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
    return [z["codigo"] for z in respuesta.json()]


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


def test_lista_ordenada_por_turno_y_codigo(cliente):
    respuesta = cliente.get("/zonas-ruta")

    assert respuesta.status_code == 200
    assert codigos(respuesta) == ["M-1", "M-10", "T-1", "N-1", "N-9"]


@pytest.mark.parametrize(
    ("turno", "esperados"),
    [
        ("manana", ["M-1", "M-10"]),
        ("mañana", ["M-1", "M-10"]),
        ("Mañana", ["M-1", "M-10"]),
        ("tarde", ["T-1"]),
        ("noche", ["N-1", "N-9"]),
    ],
)
def test_filtro_por_turno(cliente, turno, esperados):
    respuesta = cliente.get("/zonas-ruta", params={"turno": turno})

    assert respuesta.status_code == 200
    assert codigos(respuesta) == esperados
    assert all(z["turno"] == respuesta.json()[0]["turno"] for z in respuesta.json())


def test_turno_se_devuelve_sin_enie(cliente):
    respuesta = cliente.get("/zonas-ruta", params={"turno": "mañana"})

    assert {z["turno"] for z in respuesta.json()} == {"manana"}


def test_turno_invalido_devuelve_422(cliente):
    assert cliente.get("/zonas-ruta", params={"turno": "madrugada"}).status_code == 422


def test_detalle_n9(cliente):
    respuesta = cliente.get("/zonas-ruta/n-9")

    assert respuesta.status_code == 200
    zona = respuesta.json()
    assert zona["codigo"] == "N-9"
    assert zona["turno"] == "noche"
    assert zona["recojo_inicio"] == "23:00:00"
    assert zona["recojo_fin"] == "00:00:00"
    assert zona["revisar"] is True
    assert zona["cruza_medianoche"] is False


def test_detalle_cruza_medianoche(cliente):
    assert cliente.get("/zonas-ruta/N-1").json()["cruza_medianoche"] is True


def test_detalle_inexistente_devuelve_404(cliente):
    respuesta = cliente.get("/zonas-ruta/X-99")

    assert respuesta.status_code == 404
    assert respuesta.json()["detail"] == "Zona de ruta no encontrada"


@pytest.mark.parametrize("metodo", ["post", "put", "patch", "delete"])
def test_no_hay_endpoints_de_escritura(cliente, metodo):
    assert getattr(cliente, metodo)("/zonas-ruta/N-9").status_code == 405
