"""scripts/limpiar_datos_demo.py: dry-run por defecto y solo borra lo marcado es_demo."""

import pytest
from conftest import carga_flota, limpieza_demo, migracion_demo
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

import seed_demo
from app.models.camion import Camion
from app.models.nodo import Nodo
from app.models.ruta import Parada
from app.models.usuario import Usuario
from test_seed_demo import ruta_real


@pytest.fixture
def base_con_demo(db_limpia, monkeypatch):
    """Flota real + demo de seed_demo + usuarios demo y reales + una ruta real."""
    carga_flota.cargar(db_limpia)
    Sesion = sessionmaker(bind=db_limpia, autoflush=False)
    with Sesion() as db:
        db.add_all(
            [
                Usuario(email="conductor@ecoruta.com", nombre="Conductor Demo",
                        password_hash="x", rol="conductor"),
                Usuario(email="municipalidad3@ecoruta.com", nombre="Municipalidad Demo",
                        password_hash="x", rol="municipalidad"),
                Usuario(email="real@prueba.test", nombre="Real",
                        password_hash="x", rol="conductor"),
            ]
        )
        db.commit()
    monkeypatch.setattr(seed_demo, "SessionLocal", Sesion)
    seed_demo.main([])
    migracion_demo.migrar(db_limpia)  # marca los usuarios demo

    with Sesion() as db:
        nodo_real = Nodo(codigo="REAL-01", nombre="Nodo real", latitud=-8.11, longitud=-79.03)
        db.add(nodo_real)
        db.flush()
        camion_real = db.query(Camion).filter(Camion.placa == "CAM-T01").one()
        ruta_real(db, camion_real, [nodo_real])
    return Sesion


TABLAS_CONTADAS = (
    "camiones", "rutas", "paradas", "nodos", "lecturas", "usuarios", "vehiculos", "conductores",
)


def conteos(Sesion):
    """Conteos con SQL directo (sirven aunque falte alguna columna es_demo)."""
    with Sesion() as db:
        resultado = {
            "camiones_demo": db.scalar(text("SELECT count(*) FROM camiones WHERE es_demo"))
        }
        for tabla in TABLAS_CONTADAS:
            resultado[tabla] = db.scalar(text(f"SELECT count(*) FROM {tabla}"))
        return resultado


def test_dry_run_no_borra_nada(base_con_demo, db_limpia):
    antes = conteos(base_con_demo)

    resultado = limpieza_demo.limpiar(db_limpia)

    assert resultado.aplicado is False
    assert resultado.borradas == {
        "paradas": 6,
        "rutas": 3,
        "camiones": 3,
        "lecturas": 7,
        "nodos": 8,
        "usuarios": 1,  # municipalidad3; conductor@ lo usa conductores
    }
    assert conteos(base_con_demo) == antes


def test_main_sin_aplicar_es_dry_run(base_con_demo, db_limpia, monkeypatch, capsys):
    monkeypatch.setattr("app.database.engine", db_limpia)
    antes = conteos(base_con_demo)

    limpieza_demo.main([])

    assert "DRY-RUN" in capsys.readouterr().out
    assert conteos(base_con_demo) == antes


def test_aplicar_borra_solo_lo_demo(base_con_demo, db_limpia):
    resultado = limpieza_demo.limpiar(db_limpia, aplicar=True)

    assert resultado.aplicado is True
    assert conteos(base_con_demo) == {
        "camiones_demo": 0,
        "camiones": 37,
        "rutas": 1,
        "paradas": 1,
        "nodos": 1,
        "lecturas": 0,
        "usuarios": 2,
        "vehiculos": 3,
        "conductores": 3,
    }
    with base_con_demo() as db:
        assert db.query(Nodo).one().codigo == "REAL-01"
        emails = sorted(u.email for u in db.query(Usuario))
        assert emails == ["conductor@ecoruta.com", "real@prueba.test"]


def test_reporta_lo_que_no_puede_limpiar(base_con_demo, db_limpia):
    resultado = limpieza_demo.limpiar(db_limpia)

    assert resultado.bloqueadas["usuarios"] == ["conductor@ecoruta.com"]
    assert resultado.sin_es_demo == {
        "vehiculos": ["TCA-241", "TCA-316", "TCA-508"],
        "conductores": ["José Castillo", "Luis Rodríguez", "María Flores"],
    }


def test_nodo_demo_usado_por_parada_real_no_se_borra(base_con_demo, db_limpia):
    with base_con_demo() as db:
        nodo_demo = db.query(Nodo).filter(Nodo.codigo == "TRU-003").one()
        camion_real = db.query(Camion).filter(Camion.placa == "CAM-N01").one()
        ruta_real(db, camion_real, [nodo_demo])

    resultado = limpieza_demo.limpiar(db_limpia, aplicar=True)

    assert resultado.bloqueadas["nodos"] == ["TRU-003"]
    with base_con_demo() as db:
        assert db.query(Nodo).filter(Nodo.codigo == "TRU-003").count() == 1
        assert db.query(Parada).count() == 2  # las dos paradas reales siguen


def test_sin_columna_es_demo_no_borra_nada(base_con_demo, db_limpia):
    antes = conteos(base_con_demo)
    with db_limpia.begin() as conexion:
        conexion.execute(text("ALTER TABLE nodos DROP COLUMN es_demo"))
    try:
        with pytest.raises(limpieza_demo.ColumnasFaltantes, match="nodos"):
            limpieza_demo.limpiar(db_limpia, aplicar=True)
        assert conteos(base_con_demo) == antes
    finally:
        with db_limpia.begin() as conexion:
            conexion.execute(
                text("ALTER TABLE nodos ADD COLUMN es_demo BOOLEAN NOT NULL DEFAULT false")
            )
