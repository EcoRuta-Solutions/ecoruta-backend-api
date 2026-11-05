"""seed_demo.py solo reemplaza lo demo: no borra la flota provisional ni sus rutas."""

from datetime import date, datetime

import pytest
from conftest import carga_flota as carga
from conftest import importador
from sqlalchemy.orm import sessionmaker

import seed_demo
from app.models.camion import Camion
from app.models.punto_critico import PuntoCritico
from app.models.ruta import Ruta
from app.models.usuario import Usuario


@pytest.fixture
def sesion(db_limpia, csv_prueba, monkeypatch):
    importador.importar(db_limpia, csv_prueba)
    carga.cargar(db_limpia)
    Sesion = sessionmaker(bind=db_limpia, autoflush=False)
    with Sesion() as db:
        db.add(
            Usuario(email="conductor@prueba.test", nombre="Conductor", password_hash="x", rol="conductor")
        )
        db.commit()
    # seed_demo usa SessionLocal (base principal): se redirige a la de pruebas.
    monkeypatch.setattr(seed_demo, "SessionLocal", Sesion)
    return Sesion


def test_seed_demo_conserva_flota_provisional_y_puntos_criticos(sesion):
    with sesion() as db:
        camion_real = db.query(Camion).filter(Camion.placa == "CAM-M01").one()
        hoy = date.today()
        db.add(
            Ruta(
                fecha_inicio=hoy,
                fecha_fin=hoy,
                hora_inicio=datetime(hoy.year, hoy.month, hoy.day, 5),
                hora_fin=datetime(hoy.year, hoy.month, hoy.day, 13),
                camion_id=camion_real.id,
                estado="Pendiente",
            )
        )
        db.commit()

    seed_demo.main()
    seed_demo.main()  # dos corridas: no duplica demo

    with sesion() as db:
        assert db.query(Camion).filter(Camion.es_demo.is_(False)).count() == 37
        demo = db.query(Camion).filter(Camion.es_demo.is_(True)).all()
        assert sorted(c.placa for c in demo) == ["TCA-241", "TCA-316", "TCA-508"]
        assert all(c.estado == "operativo" for c in demo)
        assert db.query(PuntoCritico).count() == 4

        rutas = db.query(Ruta).all()
        assert len(rutas) == 4  # 3 demo + la del camión provisional
        assert sum(1 for r in rutas if r.camion.placa == "CAM-M01") == 1
