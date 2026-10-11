from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.sql import operators

from app.models.ruta import Parada, Ruta
from app.routers import rutas
from app.schemas.ruta import RutaGenerarRequest


class FakeQuery:
    def __init__(self, resultado):
        self.resultado = resultado

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.resultado


class FakeDB:
    def __init__(self, camion=None, ruta_existente=None):
        self.camion = camion
        self.ruta_existente = ruta_existente
        self.agregados = []
        self.commits = 0

    def get(self, modelo, id):
        return self.camion

    def query(self, modelo):
        return FakeQuery(self.ruta_existente)

    def add(self, obj):
        self.agregados.append(obj)

    def flush(self):
        for obj in self.agregados:
            if isinstance(obj, Ruta) and obj.id is None:
                obj.id = 1

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        pass

    def rollback(self):
        pass


def nodo(id, lat, lon, estado="critico", fill=90.0):
    return SimpleNamespace(
        id=id, latitud=lat, longitud=lon, estado=estado, fill_pct=fill
    )


def camion(turno="Mañana"):
    return SimpleNamespace(id=1, placa="ABC-123", capacidad=1000, turno=turno)


@pytest.fixture
def estados(monkeypatch):
    lista = [
        nodo(1, 0.0, 0.0),
        nodo(2, 0.0, 1.0, fill=95.0),
        nodo(3, 1.0, 1.0),
        nodo(4, 1.0, 0.0, estado="normal", fill=20.0),
    ]
    monkeypatch.setattr(rutas, "obtener_estados", lambda db: lista)
    return lista


def peticion(**extra):
    return RutaGenerarRequest(fecha=date(2026, 10, 9), camion_id=1, **extra)


def test_generar_ruta_guarda_ruta_y_paradas_en_orden(estados):
    db = FakeDB(camion=camion())

    resultado = rutas.generar_ruta(peticion(), db=db)

    paradas = [o for o in db.agregados if isinstance(o, Parada)]
    guardada = [o for o in db.agregados if isinstance(o, Ruta)][0]

    assert db.commits == 1
    assert guardada.estado == "Pendiente"
    assert guardada.camion_id == 1
    assert [p.orden for p in paradas] == [1, 2, 3]
    assert {p.nodo_id for p in paradas} == {1, 2, 3}
    assert paradas[0].nodo_id == 2  # inicia en el nodo más lleno
    assert resultado["metodo"] in {"ortools", "clarke_wright_tabu"}
    assert resultado["distancia_km"] > 0


def test_generar_ruta_respeta_inicio_id(estados):
    db = FakeDB(camion=camion())

    rutas.generar_ruta(peticion(inicio_id=3), db=db)

    paradas = [o for o in db.agregados if isinstance(o, Parada)]
    assert paradas[0].nodo_id == 3


def test_generar_ruta_turno_noche_termina_al_dia_siguiente(estados):
    db = FakeDB(camion=camion("Noche"))

    rutas.generar_ruta(peticion(), db=db)

    guardada = [o for o in db.agregados if isinstance(o, Ruta)][0]
    assert guardada.hora_inicio.hour == 22
    assert guardada.fecha_fin == date(2026, 10, 10)


def test_generar_ruta_un_solo_nodo_critico(monkeypatch):
    monkeypatch.setattr(
        rutas, "obtener_estados", lambda db: [nodo(7, 0.0, 0.0)]
    )
    db = FakeDB(camion=camion())

    rutas.generar_ruta(peticion(), db=db)

    paradas = [o for o in db.agregados if isinstance(o, Parada)]
    assert [(p.nodo_id, p.orden) for p in paradas] == [(7, 1)]


def test_generar_ruta_camion_inexistente_devuelve_404(estados):
    with pytest.raises(HTTPException) as error:
        rutas.generar_ruta(peticion(), db=FakeDB(camion=None))

    assert error.value.status_code == 404


def test_generar_ruta_sin_nodos_criticos_devuelve_404(monkeypatch):
    monkeypatch.setattr(
        rutas,
        "obtener_estados",
        lambda db: [nodo(1, 0.0, 0.0, estado="normal", fill=10.0)],
    )

    with pytest.raises(HTTPException) as error:
        rutas.generar_ruta(peticion(), db=FakeDB(camion=camion()))

    assert error.value.status_code == 404


def test_generar_ruta_inicio_no_critico_devuelve_404(estados):
    with pytest.raises(HTTPException) as error:
        rutas.generar_ruta(
            peticion(inicio_id=4), db=FakeDB(camion=camion())
        )

    assert error.value.status_code == 404


def test_generar_ruta_turno_invalido_devuelve_422(estados):
    with pytest.raises(HTTPException) as error:
        rutas.generar_ruta(
            peticion(), db=FakeDB(camion=camion("Madrugada"))
        )

    assert error.value.status_code == 422


def test_generar_ruta_duplicada_devuelve_409(estados):
    db = FakeDB(camion=camion(), ruta_existente=object())

    with pytest.raises(HTTPException) as error:
        rutas.generar_ruta(peticion(), db=db)

    assert error.value.status_code == 409


def test_schema_rechaza_fecha_invalida_y_camion_cero():
    with pytest.raises(ValidationError):
        RutaGenerarRequest(fecha="no-es-fecha", camion_id=1)

    with pytest.raises(ValidationError):
        RutaGenerarRequest(fecha=date(2026, 10, 9), camion_id=0)


def test_rutas_del_dia_incluye_rutas_que_siguen_activas():
    query = Mock()
    query.options.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = []
    db = Mock()
    db.query.return_value = query

    rutas.rutas_del_dia(db)

    condiciones = query.filter.call_args.args
    assert len(condiciones) == 2
    assert str(condiciones[0].left) == "rutas.fecha_inicio"
    assert condiciones[0].operator is operators.le
    assert str(condiciones[1].left) == "rutas.fecha_fin"
    assert condiciones[1].operator is operators.ge
