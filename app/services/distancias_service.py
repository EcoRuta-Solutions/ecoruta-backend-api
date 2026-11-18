"""Matriz de distancias entre puntos críticos para el optimizador de rutas.

1. Si existe la caché de OSRM (data/matriz_distancias.json, la genera
   scripts/calcular_matriz_distancias.py) y cubre TODOS los puntos pedidos con
   las mismas coordenadas, se usan esas distancias por calles: metodo "osrm".
2. Si no, se usa haversine × OPTIMIZADOR_FACTOR_CIRCUITO: metodo
   "haversine_aprox", para que quede a la vista que es una aproximación.

No se mezclan métodos en una misma matriz.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from app import config
from app.services.optimizador_service import haversine_km

RAIZ = Path(__file__).resolve().parents[2]

METODO_OSRM = "osrm"
METODO_HAVERSINE = "haversine_aprox"
# Coordenadas con 6 decimales (~10 cm): si cambian, la caché ya no aplica a ese punto.
DECIMALES = 6


@dataclass(frozen=True)
class Punto:
    codigo: str
    lat: float
    lon: float


@dataclass
class MatrizDistancias:
    km: list[list[float]]
    metodo: str


def archivo_cache() -> Path:
    ruta = Path(config.MATRIZ_DISTANCIAS_ARCHIVO)
    return ruta if ruta.is_absolute() else RAIZ / ruta


def clave_coordenada(lat: float, lon: float) -> list[float]:
    return [round(lat, DECIMALES), round(lon, DECIMALES)]


def cargar_cache(ruta: Path | None = None) -> dict | None:
    ruta = ruta or archivo_cache()
    if not ruta.is_file():
        return None
    try:
        with open(ruta, encoding="utf-8") as archivo:
            datos = json.load(archivo)
    except (OSError, ValueError):
        return None
    if not isinstance(datos, dict) or "codigos" not in datos or "distancias_m" not in datos:
        return None
    return datos


def _desde_cache(puntos: list[Punto], cache: dict) -> list[list[float]] | None:
    indice = {codigo: i for i, codigo in enumerate(cache["codigos"])}
    coordenadas = cache.get("coordenadas", {})
    posiciones = []
    for punto in puntos:
        i = indice.get(punto.codigo)
        if i is None or coordenadas.get(punto.codigo) != clave_coordenada(punto.lat, punto.lon):
            return None
        posiciones.append(i)

    distancias = cache["distancias_m"]
    km = []
    for i in posiciones:
        fila = []
        for j in posiciones:
            valor = distancias[i][j]
            if valor is None:  # OSRM no encontró camino: no se completa a mano
                return None
            fila.append(valor / 1000)
        km.append(fila)
    return km


def matriz_haversine(puntos: list[Punto]) -> list[list[float]]:
    factor = config.OPTIMIZADOR_FACTOR_CIRCUITO
    return [
        [
            0.0 if i == j else haversine_km(a.lat, a.lon, b.lat, b.lon) * factor
            for j, b in enumerate(puntos)
        ]
        for i, a in enumerate(puntos)
    ]


def matriz_para_puntos(puntos: list[Punto], cache: dict | None = None) -> MatrizDistancias:
    cache = cache if cache is not None else cargar_cache()
    if cache is not None:
        km = _desde_cache(puntos, cache)
        if km is not None:
            return MatrizDistancias(km=km, metodo=METODO_OSRM)
    return MatrizDistancias(km=matriz_haversine(puntos), metodo=METODO_HAVERSINE)
