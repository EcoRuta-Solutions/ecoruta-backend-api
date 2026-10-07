from __future__ import annotations

import math
from typing import Any, Sequence

from ortools.constraint_solver import pywrapcp, routing_enums_pb2


# Radio medio de la Tierra en kilómetros.
RADIO_TIERRA_KM = 6371.0088

# OR-Tools trabaja mejor con costos enteros.
METROS_POR_KILOMETRO = 1000


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

    a = min(1.0, max(0.0, a))

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return RADIO_TIERRA_KM * c


def construir_matriz_distancias(
    nodos: Sequence[Any],
) -> list[list[float]]:
    """
    Construye una matriz simétrica de distancias entre los nodos.

    Cada nodo debe tener:
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
    Posteriormente podrá conectarse con OSRM
    para obtener distancias reales por carretera.
    """
    return haversine_km(
        origen.latitud,
        origen.longitud,
        destino.latitud,
        destino.longitud,
    )


def optimizar_con_ortools(
    nodos: Sequence[Any],
    indice_inicio: int = 0,
    tiempo_maximo_segundos: int = 5,
) -> list[int]:
    """
    Calcula un orden recomendado de visita utilizando OR-Tools.

    Para esta primera versión del piloto:
    - Se utiliza un solo vehículo.
    - El nodo indicado por indice_inicio funciona como inicio y retorno.
    - La matriz de costos se basa en distancia Haversine.
    - Se devuelve una lista con los IDs de los nodos en el orden
      recomendado, sin repetir el nodo inicial al final.
    """
    if not nodos:
        return []

    if indice_inicio < 0 or indice_inicio >= len(nodos):
        raise ValueError("indice_inicio fuera del rango de nodos")

    if tiempo_maximo_segundos <= 0:
        raise ValueError("tiempo_maximo_segundos debe ser mayor que cero")

    if len(nodos) == 1:
        return [nodos[0].id]

    matriz_distancias = construir_matriz_distancias(nodos)

    # OR-Tools utiliza costos enteros. Convertimos kilómetros a metros.
    matriz_costos = [
        [
            int(round(distancia * METROS_POR_KILOMETRO))
            for distancia in fila
        ]
        for fila in matriz_distancias
    ]

    manager = pywrapcp.RoutingIndexManager(
        len(matriz_costos),
        1,
        indice_inicio,
    )

    routing = pywrapcp.RoutingModel(manager)

    def distancia_callback(from_index: int, to_index: int) -> int:
        """Devuelve el costo de viajar entre dos nodos."""
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)

        return matriz_costos[from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(
        distancia_callback
    )

    routing.SetArcCostEvaluatorOfAllVehicles(
        transit_callback_index
    )

    search_parameters = (
        pywrapcp.DefaultRoutingSearchParameters()
    )

    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )

    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )

    search_parameters.time_limit.seconds = tiempo_maximo_segundos

    solution = routing.SolveWithParameters(
        search_parameters
    )

    if solution is None:
        raise RuntimeError(
            "OR-Tools no pudo encontrar una ruta válida"
        )

    orden = []

    index = routing.Start(0)

    while not routing.IsEnd(index):
        node_index = manager.IndexToNode(index)
        orden.append(nodos[node_index].id)

        index = solution.Value(
            routing.NextVar(index)
        )

    return orden
