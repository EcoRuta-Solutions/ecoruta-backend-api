from __future__ import annotations

import math
from typing import Any, Sequence


# Radio medio de la Tierra en kilómetros.
RADIO_TIERRA_KM = 6371.0088


def haversine_km(
    latitud_origen: float,
    longitud_origen: float,
    latitud_destino: float,
    longitud_destino: float,
) -> float:
    """
    Calcula la distancia en línea recta entre dos coordenadas GPS
    utilizando la fórmula de Haversine.

    Retorna la distancia en kilómetros.
    """
    lat1 = math.radians(latitud_origen)
    lon1 = math.radians(longitud_origen)
    lat2 = math.radians(latitud_destino)
    lon2 = math.radians(longitud_destino)

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    # Evita pequeños errores numéricos que podrían dejar el valor
    # ligeramente fuera del intervalo válido para asin.
    a = min(1.0, max(0.0, a))

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return RADIO_TIERRA_KM * c


def construir_matriz_distancias(
    nodos: Sequence[Any],
) -> list[list[float]]:
    """
    Construye una matriz simétrica de distancias entre los nodos.

    Cada nodo debe tener los atributos:
    - latitud
    - longitud

    La posición [i][j] representa la distancia entre el nodo i
    y el nodo j en kilómetros.
    """
    cantidad = len(nodos)

    matriz = [
        [0.0 for _ in range(cantidad)]
        for _ in range(cantidad)
    ]

    for i in range(cantidad):
        for j in range(i + 1, cantidad):
            distancia = haversine_km(
                nodos[i].latitud,
                nodos[i].longitud,
                nodos[j].latitud,
                nodos[j].longitud,
            )

            matriz[i][j] = distancia
            matriz[j][i] = distancia

    return matriz


def calcular_distancia(
    origen: Any,
    destino: Any,
) -> float:
    """
    Punto central para calcular la distancia entre dos nodos.

    Actualmente utiliza Haversine.
    Posteriormente esta función podrá conectarse con OSRM
    para obtener distancias reales por carretera.
    """
    return haversine_km(
        origen.latitud,
        origen.longitud,
        destino.latitud,
        destino.longitud,
    )
