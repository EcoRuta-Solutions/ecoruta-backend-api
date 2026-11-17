"""scripts/migrar_unificar_flota.py: idempotente, no cambia filas y marca solo lo demo."""

import pytest
from sqlalchemy import inspect, text

import seed_demo
from conftest import migracion_flota


def columnas(engine, tabla):
    return {c["name"]: c for c in inspect(engine).get_columns(tabla)}


@pytest.fixture
def base_vieja(db_limpia):
    """Deja las tablas como estaban antes de la unificación y mete filas con SQL."""
    with db_limpia.begin() as c:
        c.execute(text("ALTER TABLE conductores DROP COLUMN camion_id"))
        c.execute(text("ALTER TABLE conductores DROP COLUMN es_demo"))
        c.execute(text("ALTER TABLE vehiculos DROP COLUMN es_demo"))
        c.execute(text("ALTER TABLE camiones DROP COLUMN tipo"))
        c.execute(text("ALTER TABLE camiones DROP COLUMN activo"))
        c.execute(text("UPDATE camiones SET turno = 'manana' WHERE turno IS NULL"))
        c.execute(text("ALTER TABLE camiones ALTER COLUMN turno SET NOT NULL"))
        c.execute(text("ALTER TABLE vehiculos ALTER COLUMN capacidad_toneladas SET DEFAULT 8"))
        c.execute(
            text(
                "INSERT INTO vehiculos (placa, tipo, capacidad_toneladas, estado, activo) VALUES "
                "('TCA-241', 'Compactador', 8, 'operativo', true), "
                "('ABC-123', 'Compactador', 8, 'operativo', true)"
            )
        )
        c.execute(
            text(
                "INSERT INTO conductores (nombre, telefono, categoria_licencia, estado, activo) VALUES "
                "('Luis Rodríguez', '', 'A-IIb', 'disponible', true), "
                "('Conductora Real', '', 'A-IIb', 'disponible', true)"
            )
        )
    yield db_limpia
    # Deja el esquema como lo crea create_all para las demás pruebas.
    migracion_flota.migrar(db_limpia)


def test_migracion_es_idempotente_y_marca_solo_demo(base_vieja):
    primera = migracion_flota.migrar(base_vieja)
    segunda = migracion_flota.migrar(base_vieja)

    assert primera == {"vehiculos": 1, "conductores": 1}
    assert segunda == {"vehiculos": 0, "conductores": 0}

    camiones = columnas(base_vieja, "camiones")
    assert {"tipo", "activo"} <= camiones.keys()
    assert camiones["turno"]["nullable"] is True
    assert camiones["tipo"]["nullable"] is True
    conductores = columnas(base_vieja, "conductores")
    assert {"camion_id", "es_demo"} <= conductores.keys()
    vehiculos = columnas(base_vieja, "vehiculos")
    assert vehiculos["capacidad_toneladas"]["nullable"] is True
    assert vehiculos["capacidad_toneladas"]["default"] is None

    fks = inspect(base_vieja).get_foreign_keys("conductores")
    assert any(
        fk["constrained_columns"] == ["camion_id"] and fk["referred_table"] == "camiones"
        for fk in fks
    )

    with base_vieja.connect() as c:
        assert dict(c.execute(text("SELECT placa, es_demo FROM vehiculos")).all()) == {
            "TCA-241": True,
            "ABC-123": False,
        }
        assert dict(c.execute(text("SELECT nombre, es_demo FROM conductores")).all()) == {
            "Luis Rodríguez": True,
            "Conductora Real": False,
        }
        # No cambia filas existentes: la capacidad (aunque sea el 8 viejo) queda igual.
        assert set(c.scalars(text("SELECT capacidad_toneladas FROM vehiculos"))) == {8}


def test_vehiculo_nuevo_sin_capacidad_queda_null(base_vieja):
    migracion_flota.migrar(base_vieja)
    with base_vieja.begin() as c:
        c.execute(text("INSERT INTO vehiculos (placa, tipo, estado, activo) VALUES ('XYZ-999', 'x', 'operativo', true)"))
        assert c.scalar(text("SELECT capacidad_toneladas FROM vehiculos WHERE placa = 'XYZ-999'")) is None


def test_nombres_demo_coinciden_con_seed():
    assert {n for n, *_ in seed_demo.CONDUCTORES} == set(
        migracion_flota.NOMBRES_CONDUCTORES_DEMO
    )
    assert {p for p, *_ in seed_demo.CAMIONES} == set(migracion_flota.PLACAS_DEMO)
