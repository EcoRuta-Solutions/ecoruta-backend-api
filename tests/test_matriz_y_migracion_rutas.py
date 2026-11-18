"""Matriz de distancias (OSRM por bloques, caché) y migración de paradas a puntos críticos.

Las llamadas a OSRM se simulan: estas pruebas no salen a la red.
"""

import io
import json
from datetime import datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

from app import config
from app.models.camion import Camion
from app.models.punto_critico import PuntoCritico
from app.models.ruta import Parada, Ruta
from app.services import distancias_service as ds
from conftest import importador, matriz_osrm, migracion_rutas

PUNTOS = [ds.Punto(f"P-{i}", -8.10 + i * 0.001, -79.03 - i * 0.001) for i in range(5)]


# --- Matriz en caché -------------------------------------------------------------------


def cache_de(puntos, metros):
    return {
        "codigos": [p.codigo for p in puntos],
        "coordenadas": {p.codigo: ds.clave_coordenada(p.lat, p.lon) for p in puntos},
        "distancias_m": metros,
    }


def test_matriz_desde_cache_es_osrm_y_respeta_el_orden_pedido():
    metros = [[0 if i == j else (i + 1) * 100 + j for j in range(5)] for i in range(5)]
    cache = cache_de(PUNTOS, metros)

    matriz = ds.matriz_para_puntos([PUNTOS[3], PUNTOS[1]], cache=cache)

    assert matriz.metodo == "osrm"
    assert matriz.km == [[0.0, 0.401], [0.203, 0.0]]  # asimétrica, tal cual OSRM


@pytest.mark.parametrize(
    "romper",
    [
        lambda c: c["codigos"].remove("P-4"),  # falta un punto
        lambda c: c["coordenadas"].__setitem__("P-1", [0, 0]),  # el punto se movió
        lambda c: c["distancias_m"][1].__setitem__(2, None),  # OSRM sin camino
    ],
)
def test_cache_incompleta_vuelve_a_haversine(romper):
    cache = cache_de(PUNTOS, [[0 if i == j else 500 for j in range(5)] for i in range(5)])
    romper(cache)

    matriz = ds.matriz_para_puntos(PUNTOS, cache=cache)

    assert matriz.metodo == "haversine_aprox"


def test_haversine_usa_el_factor_de_circuito(monkeypatch):
    monkeypatch.setattr(config, "OPTIMIZADOR_FACTOR_CIRCUITO", 1.0)
    base = ds.matriz_haversine(PUNTOS[:2])[0][1]
    monkeypatch.setattr(config, "OPTIMIZADOR_FACTOR_CIRCUITO", 1.3)

    assert ds.matriz_haversine(PUNTOS[:2])[0][1] == pytest.approx(base * 1.3)
    assert ds.matriz_haversine(PUNTOS[:2])[0][0] == 0


def test_archivo_inexistente_o_corrupto_no_es_cache(tmp_path):
    assert ds.cargar_cache(tmp_path / "no.json") is None
    roto = tmp_path / "roto.json"
    roto.write_text("{no es json", encoding="utf-8")
    assert ds.cargar_cache(roto) is None


# --- Script OSRM ---------------------------------------------------------------------


def test_consultar_bloque_arma_la_url_de_osrm(monkeypatch):
    pedidas = []

    class Respuesta(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def urlopen(peticion, timeout):
        pedidas.append(peticion)
        cuerpo = {"code": "Ok", "distances": [[0, 120.5]]}
        return Respuesta(json.dumps(cuerpo).encode())

    monkeypatch.setattr(matriz_osrm.urllib.request, "urlopen", urlopen)

    distancias = matriz_osrm.consultar_bloque("http://osrm.prueba/", [PUNTOS[0]], [PUNTOS[0], PUNTOS[1]])

    assert distancias == [[0, 120.5]]
    url = pedidas[0].full_url
    assert url.startswith("http://osrm.prueba/table/v1/driving/-79.030000,-8.100000;")
    assert "sources=0&destinations=1;2&annotations=distance" in url
    assert pedidas[0].get_header("User-agent") == matriz_osrm.USER_AGENT


def test_guardar_y_releer_como_osrm(tmp_path):
    matriz = [[0 if i == j else 700 for j in range(5)] for i in range(5)]
    ruta = tmp_path / "data" / "matriz.json"

    matriz_osrm.guardar(PUNTOS, matriz, ruta, "http://osrm.prueba")

    cache = ds.cargar_cache(ruta)
    assert cache["fuente"] == "osrm"
    resultado = ds.matriz_para_puntos(PUNTOS, cache=cache)
    assert resultado.metodo == "osrm"
    assert resultado.km[0][1] == 0.7


# --- Migración -------------------------------------------------------------------------


@pytest.fixture
def base_vieja(db_limpia):
    """Deja paradas/rutas como antes del cambio (sin punto_critico_id ni columnas de turno)."""
    with db_limpia.begin() as c:
        c.execute(text("ALTER TABLE paradas DROP COLUMN punto_critico_id"))
        c.execute(text("ALTER TABLE paradas ALTER COLUMN nodo_id SET NOT NULL"))
        for columna in ("turno", "distancia_km", "tiempo_estimado_min", "metodo_distancia"):
            c.execute(text(f"ALTER TABLE rutas DROP COLUMN {columna}"))
    yield db_limpia
    migracion_rutas.migrar(db_limpia)


def test_migracion_es_idempotente(base_vieja):
    migracion_rutas.migrar(base_vieja)
    migracion_rutas.migrar(base_vieja)

    inspector = inspect(base_vieja)
    paradas = {c["name"]: c for c in inspector.get_columns("paradas")}
    rutas = {c["name"] for c in inspector.get_columns("rutas")}
    assert paradas["nodo_id"]["nullable"] is True
    assert paradas["punto_critico_id"]["nullable"] is True
    assert {"turno", "distancia_km", "tiempo_estimado_min", "metodo_distancia"} <= rutas
    assert any(
        fk["constrained_columns"] == ["punto_critico_id"] and fk["referred_table"] == "puntos_criticos"
        for fk in inspector.get_foreign_keys("paradas")
    )
    checks = [c["name"] for c in inspector.get_check_constraints("paradas")]
    assert checks.count("ck_paradas_nodo_o_punto") == 1


def test_parada_sin_nodo_ni_punto_se_rechaza(db_limpia, csv_prueba):
    importador.importar(db_limpia, csv_prueba)
    Sesion = sessionmaker(bind=db_limpia)
    with Sesion() as db:
        camion = Camion(placa="CAM-M01", turno="manana")
        db.add(camion)
        db.flush()
        ruta = Ruta(fecha_inicio=datetime(2026, 1, 1).date(), fecha_fin=datetime(2026, 1, 1).date(),
                    hora_inicio=datetime(2026, 1, 1, 5), hora_fin=datetime(2026, 1, 1, 13),
                    camion_id=camion.id, estado="Pendiente")
        db.add(ruta)
        db.flush()
        punto = db.query(PuntoCritico).first()
        db.add(Parada(ruta_id=ruta.id, punto_critico_id=punto.id, orden=1))
        db.flush()  # con punto: válida
        db.add(Parada(ruta_id=ruta.id, orden=2))
        with pytest.raises(Exception, match="ck_paradas_nodo_o_punto"):
            db.flush()
