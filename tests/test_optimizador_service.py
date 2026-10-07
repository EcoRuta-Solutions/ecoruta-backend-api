from types import SimpleNamespace

import pytest

from app.services import optimizador_service


def crear_nodo(
    latitud: float,
    longitud: float,
) -> SimpleNamespace:
    return SimpleNamespace(
        latitud=latitud,
        longitud=longitud,
    )


def test_haversine_misma_coordenada_devuelve_cero() -> None:
    distancia = optimizador_service.haversine_km(
        -8.1116,
        -79.0288,
        -8.1116,
        -79.0288,
    )

    assert distancia == pytest.approx(0.0)


def test_haversine_distancia_de_un_grado_en_ecuador() -> None:
    distancia = optimizador_service.haversine_km(
        0.0,
        0.0,
        0.0,
        1.0,
    )

    assert distancia == pytest.approx(111.195, abs=0.01)


def test_calcular_distancia_usa_coordenadas_del_nodo() -> None:
    origen = crear_nodo(0.0, 0.0)
    destino = crear_nodo(0.0, 1.0)

    distancia = optimizador_service.calcular_distancia(
        origen,
        destino,
    )

    assert distancia == pytest.approx(111.195, abs=0.01)


def test_matriz_distancias_es_simetrica_y_tiene_diagonal_cero() -> None:
    nodos = [
        crear_nodo(0.0, 0.0),
        crear_nodo(0.0, 1.0),
        crear_nodo(1.0, 0.0),
    ]

    matriz = optimizador_service.construir_matriz_distancias(nodos)

    assert len(matriz) == 3
    assert all(len(fila) == 3 for fila in matriz)

    for i in range(3):
        assert matriz[i][i] == pytest.approx(0.0)

        for j in range(3):
            assert matriz[i][j] == pytest.approx(matriz[j][i])


def test_matriz_distancias_calcula_valores_esperados() -> None:
    nodos = [
        crear_nodo(0.0, 0.0),
        crear_nodo(0.0, 1.0),
    ]

    matriz = optimizador_service.construir_matriz_distancias(nodos)

    assert matriz[0][1] == pytest.approx(111.195, abs=0.01)
    assert matriz[1][0] == pytest.approx(111.195, abs=0.01)
