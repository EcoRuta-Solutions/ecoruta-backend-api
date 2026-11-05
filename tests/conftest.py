"""Fixtures con base de datos para las pruebas que necesitan PostGIS.

Usan una base aparte: `TEST_DATABASE_URL` si está definida o, si no, la de
`DATABASE_URL` con el sufijo `_test` (p. ej. `ecoruta_db_test`). Nunca tocan la
base principal. Si PostgreSQL no responde, esas pruebas se saltan.
"""

import csv
import importlib.util
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from app.config import DATABASE_URL
from app.database import Base
from app.models.punto_critico import PuntoCritico
from app.models.usuario import Usuario


def _cargar_importador():
    """Carga scripts/importar_puntos_criticos.py (scripts/ no es un paquete)."""
    ruta = Path(__file__).resolve().parents[1] / "scripts" / "importar_puntos_criticos.py"
    spec = importlib.util.spec_from_file_location("importar_puntos_criticos", ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


importador = _cargar_importador()

TABLAS_PRUEBA = [Usuario.__table__, PuntoCritico.__table__]

CABECERA_CSV = [
    "codigo",
    "estado",
    "priorizacion_obligatoria",
    "lat",
    "lon",
    "este_utm17s",
    "norte_utm17s",
    "direccion",
    "referencia",
]

# Cuatro filas reales del listado oficial.
FILAS_CSV_PRUEBA = [
    ["130101-1", "Potencial", "SI", "-8.084408", "-79.045583", "715371", "9105854",
     "Avenida Metropolitana II.", "Espaldas de Makro."],
    ["130101-2", "Recuperado", "NO", "-8.094435", "-79.038368", "716161", "9104741",
     "Avenida Pablo Cassals con la calle Rivera.", "Entre Turismo Dias y Emtrafesa."],
    ["130101-3", "Potencial", "SI", "-8.116713", "-79.016488", "718561", "9102265",
     "Avenida América del Sur cruce con la avenida Francisco de Zela.", "Estadio Chan-Chan."],
    ["130101-4", "Recuperado", "NO", "-8.09172", "-79.022761", "717883", "9105033",
     "Jirón Pucará con la calle Los Amautas.", ""],
]


def _url_pruebas():
    if os.getenv("TEST_DATABASE_URL"):
        return make_url(os.environ["TEST_DATABASE_URL"])
    if not DATABASE_URL:
        return None
    principal = make_url(DATABASE_URL)
    return principal.set(database=f"{principal.database}_test")


def _crear_base_si_falta(url) -> None:
    admin = create_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        with admin.connect() as conexion:
            existe = conexion.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :nombre"),
                {"nombre": url.database},
            )
            if not existe:
                conexion.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def engine_pruebas():
    url = _url_pruebas()
    if url is None:
        pytest.skip("Sin DATABASE_URL ni TEST_DATABASE_URL")
    if DATABASE_URL:
        principal = make_url(DATABASE_URL)
        if (url.host, url.port, url.database) == (
            principal.host,
            principal.port,
            principal.database,
        ):
            pytest.fail("La base de pruebas no puede ser la base principal")

    try:
        _crear_base_si_falta(url)
    except OperationalError:
        pytest.skip("PostgreSQL no disponible para las pruebas con base de datos")

    engine = create_engine(url)
    with engine.begin() as conexion:
        conexion.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.drop_all(engine, tables=TABLAS_PRUEBA)
    Base.metadata.create_all(engine, tables=TABLAS_PRUEBA)

    yield engine

    engine.dispose()


@pytest.fixture
def db_limpia(engine_pruebas):
    with engine_pruebas.begin() as conexion:
        conexion.execute(
            text("TRUNCATE puntos_criticos, usuarios RESTART IDENTITY")
        )
    return engine_pruebas


@pytest.fixture
def escribir_csv(tmp_path):
    """Escribe un CSV con la cabecera oficial (y BOM) y devuelve su ruta."""

    def escribir(filas, nombre="puntos.csv"):
        ruta = tmp_path / nombre
        with open(ruta, "w", encoding="utf-8-sig", newline="") as archivo:
            escritor = csv.writer(archivo)
            escritor.writerow(CABECERA_CSV)
            escritor.writerows(filas)
        return ruta

    return escribir


@pytest.fixture
def csv_prueba(escribir_csv):
    return escribir_csv(FILAS_CSV_PRUEBA)
