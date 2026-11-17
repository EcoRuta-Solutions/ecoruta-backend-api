"""seed_demo.py solo reemplaza lo demo y no corre sobre datos reales sin --force."""

import csv
from datetime import date, datetime

import pytest
from conftest import carga_flota as carga
from conftest import importador, importador_zonas, migracion_demo
from sqlalchemy.orm import sessionmaker

import seed_demo
from app.models.camion import Camion
from app.models.conductor import Conductor
from app.models.lectura import Lectura
from app.models.nodo import Nodo
from app.models.punto_critico import PuntoCritico
from app.models.ruta import Parada, Ruta
from app.models.usuario import Usuario
from app.models.vehiculo import Vehiculo
from test_importar_rutas_zona import CABECERA, FILAS_PRUEBA


@pytest.fixture
def sesion(db_limpia, monkeypatch):
    """Base con flota provisional y un conductor; seed_demo apunta a ella."""
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


def ruta_real(db, camion, nodos):
    hoy = date.today()
    ruta = Ruta(
        fecha_inicio=hoy,
        fecha_fin=hoy,
        hora_inicio=datetime(hoy.year, hoy.month, hoy.day, 5),
        hora_fin=datetime(hoy.year, hoy.month, hoy.day, 13),
        camion_id=camion.id,
        estado="Pendiente",
    )
    db.add(ruta)
    db.flush()
    for orden, nodo in enumerate(nodos, start=1):
        db.add(Parada(ruta_id=ruta.id, nodo_id=nodo.id, orden=orden))
    db.commit()
    return ruta.id


# --- Guardas -------------------------------------------------------------------


def test_se_niega_si_hay_puntos_criticos(sesion, db_limpia, csv_prueba):
    importador.importar(db_limpia, csv_prueba)

    with pytest.raises(SystemExit, match="puntos_criticos"):
        seed_demo.main([])

    with sesion() as db:
        assert db.query(Camion).filter(Camion.es_demo.is_(True)).count() == 0
        assert db.query(Nodo).count() == 0


def test_se_niega_si_hay_zonas_ruta(sesion, db_limpia, tmp_path):
    archivo = tmp_path / "zonas.csv"
    with open(archivo, "w", encoding="utf-8", newline="") as salida:
        escritor = csv.writer(salida)
        escritor.writerow(CABECERA)
        escritor.writerows(FILAS_PRUEBA)
    importador_zonas.importar(db_limpia, archivo)

    with pytest.raises(SystemExit, match="zonas_ruta"):
        seed_demo.main([])

    with sesion() as db:
        assert db.query(Ruta).count() == 0


def test_sin_datos_reales_corre_sin_force(sesion):
    seed_demo.main([])

    with sesion() as db:
        assert db.query(Ruta).filter(Ruta.es_demo.is_(True)).count() == 3


# --- Solo toca lo demo -----------------------------------------------------------


def test_force_conserva_flota_provisional_y_puntos_criticos(sesion, db_limpia, csv_prueba):
    importador.importar(db_limpia, csv_prueba)
    with sesion() as db:
        camion_real = db.query(Camion).filter(Camion.placa == "CAM-M01").one()
        ruta_real(db, camion_real, [])

    seed_demo.main(["--force"])
    seed_demo.main(["--force"])  # dos corridas: no duplica demo

    with sesion() as db:
        assert db.query(Camion).filter(Camion.es_demo.is_(False)).count() == 37
        demo = db.query(Camion).filter(Camion.es_demo.is_(True)).all()
        assert sorted(c.placa for c in demo) == ["TCA-241", "TCA-316", "TCA-508"]
        assert all(c.estado == "operativo" for c in demo)
        assert db.query(PuntoCritico).count() == 4

        rutas = db.query(Ruta).all()
        assert len(rutas) == 4  # 3 demo + la del camión provisional
        assert sum(1 for r in rutas if r.camion.placa == "CAM-M01") == 1
        assert sum(1 for r in rutas if r.es_demo) == 3
        assert db.query(Nodo).filter(Nodo.es_demo.is_(True)).count() == 8
        assert db.query(Lectura).count() == 7  # TRU-008 no tiene lectura


def test_no_borra_paradas_reales(sesion):
    seed_demo.main([])
    with sesion() as db:
        nodo_real = Nodo(codigo="REAL-01", nombre="Nodo real", latitud=-8.11, longitud=-79.03)
        db.add(nodo_real)
        db.flush()
        nodo_demo = db.query(Nodo).filter(Nodo.codigo == "TRU-001").one()
        camion_real = db.query(Camion).filter(Camion.placa == "CAM-N01").one()
        # Una parada en un nodo real y otra en un nodo demo: ninguna debe borrarse.
        id_real = ruta_real(db, camion_real, [nodo_real, nodo_demo])
        nodo_demo_id = nodo_demo.id

    seed_demo.main([])

    with sesion() as db:
        ruta = db.get(Ruta, id_real)
        assert ruta is not None and ruta.es_demo is False
        paradas = sorted(ruta.paradas, key=lambda p: p.orden)
        assert [p.nodo.codigo for p in paradas] == ["REAL-01", "TRU-001"]
        assert db.query(Nodo).filter(Nodo.codigo == "REAL-01").count() == 1
        # El nodo demo se actualiza en su lugar: mismo id, sin duplicarse.
        assert db.query(Nodo).filter(Nodo.codigo == "TRU-001").one().id == nodo_demo_id
        assert db.query(Ruta).filter(Ruta.es_demo.is_(True)).count() == 3


def test_rutas_demo_usan_horario_del_turno_manana(sesion):
    seed_demo.main([])

    with sesion() as db:
        for ruta in db.query(Ruta).filter(Ruta.es_demo.is_(True)):
            assert (ruta.hora_inicio.hour, ruta.hora_fin.hour) == (5, 13)


def test_codigos_demo_de_la_migracion_coinciden_con_seed():
    assert {codigo for codigo, *_ in seed_demo.NODOS} == set(
        migracion_demo.CODIGOS_NODOS_DEMO
    )


# --- Flota demo solo en camiones ---------------------------------------------------


def test_no_crea_vehiculos_y_conductores_usan_camion(sesion):
    seed_demo.main([])
    with sesion() as db:
        ids_antes = {c.placa: c.id for c in db.query(Camion).filter(Camion.es_demo.is_(True))}

    seed_demo.main([])  # segunda corrida: actualiza en su lugar

    with sesion() as db:
        assert db.query(Vehiculo).count() == 0
        demo = {c.placa: c for c in db.query(Camion).filter(Camion.es_demo.is_(True))}
        assert {p: c.id for p, c in demo.items()} == ids_antes  # mismos ids
        assert demo["TCA-508"].tipo == "Volquete"
        conductores = {k.nombre: k for k in db.query(Conductor)}
        assert set(conductores) == {"Luis Rodríguez", "María Flores", "José Castillo"}
        assert all(k.es_demo for k in conductores.values())
        assert all(k.vehiculo_id is None for k in conductores.values())
        assert conductores["Luis Rodríguez"].camion_id == demo["TCA-241"].id
        assert conductores["José Castillo"].camion_id == demo["TCA-316"].id


def test_conductor_real_en_camion_demo_no_rompe_el_seed(sesion):
    seed_demo.main([])
    with sesion() as db:
        camion_demo = db.query(Camion).filter(Camion.placa == "TCA-241").one()
        db.add(Conductor(nombre="Conductora Real", camion_id=camion_demo.id))
        db.commit()

    seed_demo.main([])  # antes borraba los camiones demo: aquí fallaría la FK

    with sesion() as db:
        real = db.query(Conductor).filter(Conductor.nombre == "Conductora Real").one()
        assert real.es_demo is False
        assert db.get(Camion, real.camion_id).placa == "TCA-241"
