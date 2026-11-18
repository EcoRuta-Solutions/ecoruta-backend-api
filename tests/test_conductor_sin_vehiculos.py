"""Regresión: POST /flota/conductores daba 500 (NoReferencedTableError a 'vehiculos').

Conductor declaraba ForeignKey("vehiculos.id") pero la app ya no carga el modelo
Vehiculo. En el proceso de pytest el bug quedaba oculto porque conftest importa
Vehiculo; por eso el flujo completo corre en un SUBPROCESO que importa solo
app.main (la app real), contra la base de pruebas.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app.core.turnos import Turno
from app.models.camion import Camion
from app.models.conductor import Conductor
from app.models.usuario import Usuario
from conftest import importador

RAIZ = Path(__file__).resolve().parents[1]

# Corre en un proceso limpio: solo la app real, sin conftest ni el modelo Vehiculo.
SCRIPT = r"""
import json, os, sys
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main
from app.core.security import create_access_token
from app.database import Base, get_db

def cuerpo(r):
    try:
        return r.json()
    except ValueError:  # p. ej. el 500 "Internal Server Error" en texto plano
        return r.text

salida = {"vehiculos_en_metadata": "vehiculos" in Base.metadata.tables}
engine = create_engine(os.environ["ECORUTA_URL_PRUEBA"])
Sesion = sessionmaker(bind=engine, autoflush=False)

def get_db_pruebas():
    db = Sesion()
    try:
        yield db
    finally:
        db.close()

app.main.app.dependency_overrides[get_db] = get_db_pruebas
cliente = TestClient(app.main.app, raise_server_exceptions=False)
ids = json.loads(os.environ["ECORUTA_IDS"])
muni = {"Authorization": "Bearer " + create_access_token(ids["municipalidad"], "municipalidad")}
cond = {"Authorization": "Bearer " + create_access_token(ids["conductor"], "conductor")}

r = cliente.post("/flota/conductores", headers=muni, json={
    "nombre": "Conductor real", "camion_id": ids["camion"], "usuario_id": ids["conductor"],
})
salida["crear_status"] = r.status_code
salida["crear"] = cuerpo(r)
if r.status_code != 201:
    print(json.dumps(salida))
    sys.exit(0)

r = cliente.post("/rutas/generar", headers=muni, json={"turno": "manana", "fecha": "2026-11-20"})
salida["generar_status"] = r.status_code
salida["generar_conductores"] = [x["conductor_id"] for x in r.json().get("rutas", [])]

r = cliente.get("/rutas/mias", headers=cond)
salida["mias_status"] = r.status_code
salida["mias"] = [{"camion_id": x["camion_id"], "conductor_id": x["conductor_id"],
                   "paradas": len(x["paradas"])} for x in r.json()]
print(json.dumps(salida))
"""


def test_conductor_no_declara_fk_a_vehiculos():
    destinos = sorted(fk.column.table.name for fk in Conductor.__table__.foreign_keys)

    assert destinos == ["camiones", "usuarios"]
    assert Conductor.__table__.c.vehiculo_id.nullable is True  # la columna heredada sigue


def test_crear_conductor_y_mi_ruta_con_la_app_real(db_limpia, csv_prueba, tmp_path):
    importador.importar(db_limpia, csv_prueba)  # 4 puntos críticos reales
    Sesion = sessionmaker(bind=db_limpia)
    with Sesion() as db:
        camion = Camion(placa="CAM-M01", turno=Turno.manana.value, estado="operativo")
        muni = Usuario(email="muni@prueba.test", nombre="Muni", password_hash="x", rol="municipalidad")
        conductor = Usuario(email="cond@prueba.test", nombre="Cond", password_hash="x", rol="conductor")
        db.add_all([camion, muni, conductor])
        db.commit()
        ids = {"camion": camion.id, "municipalidad": muni.id, "conductor": conductor.id}

    entorno = {
        **os.environ,
        # La URL de la base de pruebas va solo por entorno al subproceso (no se imprime).
        "ECORUTA_URL_PRUEBA": db_limpia.url.render_as_string(hide_password=False),
        "ECORUTA_IDS": json.dumps(ids),
        "OPTIMIZADOR_TIEMPO_MAX_S": "1",
        "MATRIZ_DISTANCIAS_ARCHIVO": str(tmp_path / "sin_matriz.json"),
        "PYTHONIOENCODING": "utf-8",
    }
    proceso = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=RAIZ, env=entorno,
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert proceso.returncode == 0, proceso.stderr[-2000:]
    salida = json.loads(proceso.stdout.strip().splitlines()[-1])

    # Mismas condiciones que en producción: la app no carga el modelo Vehiculo.
    assert salida["vehiculos_en_metadata"] is False
    assert salida["crear_status"] == 201, salida["crear"]
    assert salida["crear"]["camion_id"] == ids["camion"]
    assert salida["crear"]["usuario_id"] == ids["conductor"]
    assert salida["generar_status"] == 201
    assert salida["generar_conductores"] == [ids["conductor"]]
    assert salida["mias_status"] == 200
    assert salida["mias"] == [{"camion_id": ids["camion"], "conductor_id": ids["conductor"], "paradas": 4}]

    with Sesion() as db:
        guardado = db.query(Conductor).one()
        assert (guardado.camion_id, guardado.usuario_id, guardado.vehiculo_id) == (
            ids["camion"], ids["conductor"], None,
        )
