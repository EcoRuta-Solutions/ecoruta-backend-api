"""scripts/vincular_conductores_camion.py: cruza por placa, no crea camiones y reporta."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models.camion import Camion
from app.models.conductor import Conductor
from app.models.vehiculo import Vehiculo
from conftest import _cargar_script

vinculo = _cargar_script("vincular_conductores_camion")


@pytest.fixture
def datos(db_limpia):
    Sesion = sessionmaker(bind=db_limpia)
    with Sesion() as db:
        camion = Camion(placa="AAA-111", turno="manana")
        otro = Camion(placa="CCC-333", turno="tarde")
        con_pareja = Vehiculo(placa="AAA-111", tipo="Compactador")
        sin_pareja = Vehiculo(placa="BBB-222", tipo="Compactador")
        db.add_all([camion, otro, con_pareja, sin_pareja])
        db.flush()
        db.add_all(
            [
                Conductor(nombre="Con pareja", vehiculo_id=con_pareja.id),
                Conductor(nombre="Sin pareja", vehiculo_id=sin_pareja.id),
                Conductor(nombre="Sin vehiculo"),
                # Ya asignado desde la API a otro camión: no se pisa.
                Conductor(nombre="Ya asignado", vehiculo_id=con_pareja.id, camion_id=otro.id),
            ]
        )
        db.commit()
        ids = {"camion": camion.id, "otro": otro.id}
    return Sesion, ids


def camion_ids(Sesion):
    with Sesion() as db:
        return {k.nombre: k.camion_id for k in db.query(Conductor)}


def test_vincula_por_placa_y_reporta_sin_pareja(datos, db_limpia):
    Sesion, ids = datos

    resultado = vinculo.vincular(db_limpia)

    assert resultado.vinculados == 1
    assert resultado.placas_sin_pareja == ["BBB-222"]
    assert resultado.conductores_sin_pareja == [("Sin pareja", "BBB-222")]
    assert resultado.conductores_distintos == [("Ya asignado", "AAA-111", "CCC-333")]
    assert camion_ids(Sesion) == {
        "Con pareja": ids["camion"],
        "Sin pareja": None,
        "Sin vehiculo": None,
        "Ya asignado": ids["otro"],
    }


def test_es_idempotente_y_no_crea_camiones(datos, db_limpia):
    Sesion, _ = datos
    vinculo.vincular(db_limpia)
    antes = camion_ids(Sesion)

    segunda = vinculo.vincular(db_limpia)

    assert segunda.vinculados == 0
    assert camion_ids(Sesion) == antes
    with db_limpia.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM camiones")) == 2
