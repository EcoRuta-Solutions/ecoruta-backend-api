"""scripts/migrar_zonas_ruta_tramos.py: de "único por codigo" a "único por (codigo, tramo)"."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from conftest import _cargar_script

migracion = _cargar_script("migrar_zonas_ruta_tramos")

INSERTAR = (
    "INSERT INTO zonas_ruta (codigo, turno, tramo, recojo_inicio, recojo_fin) "
    "VALUES (:codigo, 'manana', :tramo, '05:30', '07:30')"
)


@pytest.fixture
def base_vieja(db_limpia):
    """zonas_ruta como estaba: tramo VARCHAR nullable e índice único solo por codigo."""
    with db_limpia.begin() as c:
        c.execute(text("ALTER TABLE zonas_ruta DROP CONSTRAINT uq_zonas_ruta_codigo_tramo"))
        c.execute(text("DROP INDEX ix_zonas_ruta_codigo"))
        c.execute(text("CREATE UNIQUE INDEX ix_zonas_ruta_codigo ON zonas_ruta (codigo)"))
        c.execute(text("ALTER TABLE zonas_ruta ALTER COLUMN tramo DROP NOT NULL"))
        c.execute(text("ALTER TABLE zonas_ruta ALTER COLUMN tramo TYPE VARCHAR"))
    yield db_limpia
    with db_limpia.begin() as c:
        c.execute(text("TRUNCATE zonas_ruta RESTART IDENTITY"))
    migracion.migrar(db_limpia)  # deja el esquema final para las demás pruebas


def insertar(engine, filas):
    with engine.begin() as c:
        for codigo, tramo in filas:
            c.execute(text(INSERTAR), {"codigo": codigo, "tramo": tramo})


def test_migracion_idempotente_sin_perder_filas(base_vieja):
    insertar(base_vieja, [("M-1", "1"), ("M-2", None), ("M-3", "")])

    primera = migracion.migrar(base_vieja)
    segunda = migracion.migrar(base_vieja)

    assert (primera.tramo_convertido, primera.unicidad_codigo_quitada, primera.restriccion_agregada) == (
        True, True, True,
    )
    assert primera.tramos_completados == 2
    assert (segunda.tramo_convertido, segunda.unicidad_codigo_quitada, segunda.restriccion_agregada) == (
        False, False, False,
    )
    with base_vieja.connect() as c:
        assert c.execute(text("SELECT codigo, tramo FROM zonas_ruta ORDER BY codigo")).all() == [
            ("M-1", 1), ("M-2", 1), ("M-3", 1),
        ]

    columnas = {col["name"]: col for col in inspect(base_vieja).get_columns("zonas_ruta")}
    assert str(columnas["tramo"]["type"]) == "INTEGER"
    assert columnas["tramo"]["nullable"] is False
    indices = {i["name"]: i for i in inspect(base_vieja).get_indexes("zonas_ruta")}
    assert indices["ix_zonas_ruta_codigo"]["unique"] is False
    unicas = inspect(base_vieja).get_unique_constraints("zonas_ruta")
    assert [(u["name"], u["column_names"]) for u in unicas] == [
        ("uq_zonas_ruta_codigo_tramo", ["codigo", "tramo"])
    ]


def test_despues_acepta_tramos_y_rechaza_el_par_repetido(base_vieja):
    migracion.migrar(base_vieja)
    insertar(base_vieja, [("M-1", 1), ("M-1", 2)])  # mismo código, otro tramo: válido

    with pytest.raises(IntegrityError):
        insertar(base_vieja, [("M-1", 2)])


def test_tramo_no_entero_detiene_la_migracion_sin_cambios(base_vieja):
    insertar(base_vieja, [("M-1", "uno"), ("M-2", None)])

    with pytest.raises(migracion.TramosInvalidos, match="M-1='uno'"):
        migracion.migrar(base_vieja)

    with base_vieja.connect() as c:
        assert c.scalar(text("SELECT tramo FROM zonas_ruta WHERE codigo = 'M-2'")) is None
    columnas = {col["name"]: col for col in inspect(base_vieja).get_columns("zonas_ruta")}
    assert str(columnas["tramo"]["type"]) == "VARCHAR"


def test_base_nueva_crea_la_tabla_final(db_limpia):
    with db_limpia.begin() as c:
        c.execute(text("DROP TABLE zonas_ruta"))

    migracion.migrar(db_limpia)

    unicas = inspect(db_limpia).get_unique_constraints("zonas_ruta")
    assert [u["column_names"] for u in unicas] == [["codigo", "tramo"]]
