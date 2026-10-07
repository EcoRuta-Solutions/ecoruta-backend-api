def comparar_optimizadores(
    nodos: Sequence[Any],
    indice_inicio: int = 0,
    tiempo_maximo_segundos: int = 5,
    iteraciones_maximas: int = 100,
    tamano_tabu: int = 10,
) -> dict[str, Any]:
    """
    Compara la solución de OR-Tools contra la solución
    de Clarke-Wright mejorada con búsqueda tabú.

    La comparación se realiza mediante la distancia total
    de cada ruta en kilómetros, incluyendo el regreso
    al nodo de inicio.

    Retorna:
    - ruta_ortools
    - distancia_ortools_km
    - ruta_heuristica
    - distancia_heuristica_km
    - diferencia_km
    - mejor_metodo
    """
    if not nodos:
        return {
            "ruta_ortools": [],
            "distancia_ortools_km": 0.0,
            "ruta_heuristica": [],
            "distancia_heuristica_km": 0.0,
            "diferencia_km": 0.0,
            "mejor_metodo": "empate",
        }

    if indice_inicio < 0 or indice_inicio >= len(nodos):
        raise ValueError("indice_inicio fuera del rango de nodos")

    matriz_distancias = construir_matriz_distancias(nodos)

    ruta_ortools = optimizar_con_ortools(
        nodos,
        indice_inicio=indice_inicio,
        tiempo_maximo_segundos=tiempo_maximo_segundos,
    )

    ruta_heuristica = optimizar_con_busqueda_tabu(
        nodos,
        indice_inicio=indice_inicio,
        iteraciones_maximas=iteraciones_maximas,
        tamano_tabu=tamano_tabu,
    )

    id_a_indice = {
        nodo.id: indice
        for indice, nodo in enumerate(nodos)
    }

    indices_ortools = [
        id_a_indice[nodo_id]
        for nodo_id in ruta_ortools
    ]

    indices_heuristica = [
        id_a_indice[nodo_id]
        for nodo_id in ruta_heuristica
    ]

    distancia_ortools = calcular_costo_ruta(
        matriz_distancias,
        indices_ortools[1:],
        indice_inicio,
    )

    distancia_heuristica = calcular_costo_ruta(
        matriz_distancias,
        indices_heuristica[1:],
        indice_inicio,
    )

    diferencia = abs(
        distancia_ortools - distancia_heuristica
    )

    if distancia_ortools < distancia_heuristica:
        mejor_metodo = "ortools"
    elif distancia_heuristica < distancia_ortools:
        mejor_metodo = "clarke_wright_tabu"
    else:
        mejor_metodo = "empate"

    return {
        "ruta_ortools": ruta_ortools,
        "distancia_ortools_km": distancia_ortools,
        "ruta_heuristica": ruta_heuristica,
        "distancia_heuristica_km": distancia_heuristica,
        "diferencia_km": diferencia,
        "mejor_metodo": mejor_metodo,
    }
