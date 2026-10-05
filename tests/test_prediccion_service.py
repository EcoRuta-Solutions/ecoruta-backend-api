from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import prediccion_service


@pytest.fixture
def nodo() -> SimpleNamespace:
    return SimpleNamespace(umbral_critico=80)


@pytest.fixture(autouse=True)
def sin_modelo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prediccion_service, "cargar_modelo", lambda: None)


def lectura(fecha: datetime, fill_pct: float) -> SimpleNamespace:
    return SimpleNamespace(timestamp=fecha, fill_pct=fill_pct)


def test_respaldo_lineal_estima_horas(nodo: SimpleNamespace) -> None:
    inicio = datetime(2026, 1, 1, tzinfo=timezone.utc)
    resultado = prediccion_service.estimar_horas_critico(
        nodo,
        [lectura(inicio, 20), lectura(inicio + timedelta(hours=1), 30)],
    )

    assert resultado["metodo"] == "lineal"
    assert resultado["horas_estimadas"] == 5
    assert resultado["fecha_estimada_critico"] == resultado["calculado_en"] + timedelta(
        hours=5
    )


def test_nodo_ya_critico_devuelve_cero(nodo: SimpleNamespace) -> None:
    instante = datetime(2026, 1, 1, tzinfo=timezone.utc)
    resultado = prediccion_service.estimar_horas_critico(
        nodo, [lectura(instante, 80)]
    )

    assert resultado["horas_estimadas"] == 0
    assert resultado["fecha_estimada_critico"] == resultado["calculado_en"]


def test_sin_lecturas_devuelve_sin_estimacion(nodo: SimpleNamespace) -> None:
    resultado = prediccion_service.estimar_horas_critico(nodo, [])

    assert resultado["horas_estimadas"] is None
    assert resultado["fecha_estimada_critico"] is None


@pytest.mark.parametrize("valores", [(25, 25), (30, 20)])
def test_tasa_cero_o_negativa_devuelve_sin_estimacion(
    nodo: SimpleNamespace, valores: tuple[float, float]
) -> None:
    inicio = datetime(2026, 1, 1, tzinfo=timezone.utc)
    resultado = prediccion_service.estimar_horas_critico(
        nodo,
        [lectura(inicio, valores[0]), lectura(inicio + timedelta(hours=1), valores[1])],
    )

    assert resultado["horas_estimadas"] is None
    assert resultado["fecha_estimada_critico"] is None