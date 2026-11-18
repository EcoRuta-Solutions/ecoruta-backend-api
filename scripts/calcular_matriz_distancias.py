r"""Calcula la matriz de distancias por calles entre los puntos críticos (OSRM /table).

Se corre UNA vez (y de nuevo solo si cambian los puntos). Guarda el resultado en
data/matriz_distancias.json, que luego usa POST /rutas/generar. Sin ese archivo
el generador usa haversine × factor de circuito y lo marca como "haversine_aprox".

Uso justo del servidor público de demostración de OSRM:
- pide la tabla por bloques equilibrados (≤ 25 puntos por lado por defecto, así
  ninguna petición pasa de 50 coordenadas y no queda un bloque de 1 punto);
- hace una pausa entre peticiones y reintenta cada bloque con espera creciente;
- solo envía coordenadas de los puntos críticos (dato público), sin datos personales.

Robustez:
- guarda el avance en data/matriz_distancias.parcial.json después de cada bloque;
  si se corta, al volver a correrlo reanuda desde ahí (si los puntos no cambiaron);
- escribe data/matriz_distancias.json SOLO si la matriz está completa y validada
  (N×N, sin nulos, diagonal en 0, distancias ≥ 0);
- si OSRM no encuentra camino entre dos puntos (null), ese par queda con la
  distancia aproximada (haversine × factor de circuito, en metros) y se informa
  cuántos fueron; el archivo los lista en "pares_aproximados".

Uso:
    .\venv\Scripts\python.exe scripts\calcular_matriz_distancias.py
    .\venv\Scripts\python.exe scripts\calcular_matriz_distancias.py --bloque 20 --pausa 1.5
    .\venv\Scripts\python.exe scripts\calcular_matriz_distancias.py --desde-cero
"""

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from app import config
from app.models.punto_critico import PuntoCritico
from app.services.distancias_service import Punto, archivo_cache, clave_coordenada
from app.services.optimizador_service import haversine_km

USER_AGENT = "EcoRuta-matriz-distancias/1.0"
# OSRM público: hasta 100 coordenadas por /table; con bloques de 25 se usan ≤ 50.
BLOQUE_MAXIMO = 50
INTENTOS_POR_BLOQUE = 4
ESPERA_BASE_S = 2.0  # 2, 4, 8… segundos entre reintentos de un mismo bloque
VERSION_PARCIAL = 1


class ErrorOsrm(RuntimeError):
    pass


class MatrizInvalida(ValueError):
    pass


@dataclass
class ResultadoMatriz:
    distancias_m: list[list[float]]
    pares_aproximados: list[tuple[int, int]] = field(default_factory=list)
    peticiones: int = 0
    bloques_reanudados: int = 0


def leer_puntos(engine: Engine) -> list[Punto]:
    with engine.connect() as conexion:
        filas = conexion.execute(
            select(
                PuntoCritico.codigo_unico,
                func.ST_Y(PuntoCritico.ubicacion),
                func.ST_X(PuntoCritico.ubicacion),
            ).order_by(PuntoCritico.id)
        ).all()
    return [Punto(codigo, lat, lon) for codigo, lat, lon in filas]


def dividir_en_bloques(n: int, tamano_maximo: int) -> list[range]:
    """Bloques de tamaño parecido (151 con máx. 25 -> 7 bloques de 21-22, no 25×6 + 1)."""
    if n <= 0:
        return []
    cantidad = math.ceil(n / tamano_maximo)
    base, resto = divmod(n, cantidad)
    bloques, inicio = [], 0
    for k in range(cantidad):
        largo = base + (1 if k < resto else 0)
        bloques.append(range(inicio, inicio + largo))
        inicio += largo
    return bloques


def consultar_bloque(
    osrm_url: str, origenes: list[Punto], destinos: list[Punto], timeout: float = 30
) -> list[list[float | None]]:
    """Distancias en metros de cada origen a cada destino (una petición OSRM /table).

    OSRM exige al menos 2 coordenadas: un bloque diagonal de 1 punto no se pide
    (ver `calcular`).
    """
    mismos = origenes == destinos
    coordenadas = origenes if mismos else origenes + destinos
    if len(coordenadas) < 2:
        raise ErrorOsrm("OSRM necesita al menos 2 coordenadas por petición")
    texto = ";".join(f"{p.lon:.6f},{p.lat:.6f}" for p in coordenadas)  # orden lon,lat
    fuentes = ";".join(str(i) for i in range(len(origenes)))
    inicio_destinos = 0 if mismos else len(origenes)
    destinos_idx = ";".join(str(inicio_destinos + i) for i in range(len(destinos)))
    url = (
        f"{osrm_url.rstrip('/')}/table/v1/driving/{texto}"
        f"?sources={fuentes}&destinations={destinos_idx}&annotations=distance"
    )

    try:
        peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            datos = json.load(respuesta)
    except urllib.error.HTTPError as error:
        cuerpo = error.read().decode("utf-8", "replace")[:300]
        raise ErrorOsrm(f"HTTP {error.code}: {cuerpo}") from error
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise ErrorOsrm(f"sin respuesta válida de OSRM: {error}") from error

    if datos.get("code") != "Ok":
        raise ErrorOsrm(f"OSRM respondió {datos.get('code')}: {datos.get('message')}")
    distancias = datos.get("distances")
    if (
        not isinstance(distancias, list)
        or len(distancias) != len(origenes)
        or any(len(fila) != len(destinos) for fila in distancias)
    ):
        raise ErrorOsrm("OSRM devolvió una tabla de tamaño inesperado")
    return distancias


def _con_reintentos(consultar, args, intentos: int, espera_base: float, dormir, etiqueta: str):
    ultimo = None
    for intento in range(intentos):
        try:
            return consultar(*args)
        except ErrorOsrm as error:
            ultimo = error
            if intento < intentos - 1:
                espera = espera_base * 2**intento
                print(f"  {etiqueta}: {error}; reintento en {espera:.0f} s", flush=True)
                dormir(espera)
    raise ErrorOsrm(f"{etiqueta} falló tras {intentos} intentos: {ultimo}")


# --- Avance parcial ------------------------------------------------------------------


def _firma(puntos: list[Punto], bloque: int) -> dict:
    return {
        "version": VERSION_PARCIAL,
        "bloque": bloque,
        "codigos": [p.codigo for p in puntos],
        "coordenadas": {p.codigo: clave_coordenada(p.lat, p.lon) for p in puntos},
    }


def _escribir_json(ruta: Path, datos: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".tmp")
    with open(temporal, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo)
    temporal.replace(ruta)  # nunca deja un archivo a medias


def _leer_parcial(ruta: Path | None, firma: dict) -> dict | None:
    """Avance guardado, solo si es de los mismos puntos y el mismo tamaño de bloque."""
    if ruta is None or not ruta.is_file():
        return None
    try:
        with open(ruta, encoding="utf-8") as archivo:
            datos = json.load(archivo)
    except (OSError, ValueError):
        return None
    if any(datos.get(k) != v for k, v in firma.items()):
        return None
    return datos


# --- Cálculo ----------------------------------------------------------------------------


def calcular(
    puntos: list[Punto],
    osrm_url: str,
    bloque: int = 25,
    pausa: float = 1.0,
    consultar=consultar_bloque,
    archivo_parcial: Path | None = None,
    intentos: int = INTENTOS_POR_BLOQUE,
    espera_base: float = ESPERA_BASE_S,
    dormir=time.sleep,
) -> ResultadoMatriz:
    n = len(puntos)
    bloques = dividir_en_bloques(n, bloque)
    firma = _firma(puntos, bloque)

    parcial = _leer_parcial(archivo_parcial, firma)
    if parcial is not None:
        matriz = parcial["distancias_m"]
        hechos = set(parcial["hechos"])
    else:
        matriz = [[None] * n for _ in range(n)]
        hechos = set()
    resultado = ResultadoMatriz(distancias_m=matriz, bloques_reanudados=len(hechos))

    pares = [(a, b) for a in range(len(bloques)) for b in range(len(bloques))]
    for numero, (a, b) in enumerate(pares, start=1):
        clave = f"{a}-{b}"
        if clave in hechos:
            continue
        filas, columnas = bloques[a], bloques[b]
        if a == b and len(filas) == 1:
            parcial_bloque = [[0.0]]  # un punto consigo mismo: no hace falta pedirlo
        else:
            if resultado.peticiones and pausa:
                dormir(pausa)
            parcial_bloque = _con_reintentos(
                consultar,
                (osrm_url, [puntos[i] for i in filas], [puntos[j] for j in columnas]),
                intentos,
                espera_base,
                dormir,
                f"bloque {numero}/{len(pares)}",
            )
            resultado.peticiones += 1
        for x, i in enumerate(filas):
            for y, j in enumerate(columnas):
                matriz[i][j] = 0.0 if i == j else parcial_bloque[x][y]
        hechos.add(clave)
        if archivo_parcial is not None:
            _escribir_json(archivo_parcial, {**firma, "hechos": sorted(hechos), "distancias_m": matriz})
        print(f"  bloque {numero}/{len(pares)} listo", flush=True)

    # Pares sin camino por calles: distancia aproximada, informada aparte.
    factor = config.OPTIMIZADOR_FACTOR_CIRCUITO
    for i in range(n):
        for j in range(n):
            if matriz[i][j] is None:
                a, b = puntos[i], puntos[j]
                matriz[i][j] = haversine_km(a.lat, a.lon, b.lat, b.lon) * factor * 1000
                resultado.pares_aproximados.append((i, j))
    return resultado


def validar(matriz, n: int) -> None:
    if not isinstance(matriz, list) or len(matriz) != n or any(
        not isinstance(fila, list) or len(fila) != n for fila in matriz
    ):
        raise MatrizInvalida(f"la matriz no es de {n}×{n}")
    for i, fila in enumerate(matriz):
        for j, valor in enumerate(fila):
            if valor is None:
                raise MatrizInvalida(f"valor nulo en [{i}][{j}]")
            if not isinstance(valor, (int, float)) or not math.isfinite(valor) or valor < 0:
                raise MatrizInvalida(f"valor inválido en [{i}][{j}]: {valor!r}")
        if fila[i] != 0:
            raise MatrizInvalida(f"la diagonal no es 0 en [{i}][{i}]")


def guardar(
    puntos: list[Punto],
    matriz,
    ruta: Path,
    osrm_url: str,
    pares_aproximados: list[tuple[int, int]] | None = None,
) -> None:
    """Escribe la matriz final solo si pasa la validación (si no, MatrizInvalida y no escribe)."""
    validar(matriz, len(puntos))
    aproximados = pares_aproximados or []
    _escribir_json(
        ruta,
        {
            "fuente": "osrm",
            "servidor": osrm_url,
            "perfil": "driving",
            "unidad": "metros",
            "generado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "codigos": [p.codigo for p in puntos],
            "coordenadas": {p.codigo: clave_coordenada(p.lat, p.lon) for p in puntos},
            "distancias_m": matriz,
            "factor_circuito_aproximados": config.OPTIMIZADOR_FACTOR_CIRCUITO,
            "pares_aproximados": [
                [puntos[i].codigo, puntos[j].codigo] for i, j in aproximados
            ],
        },
    )


def archivo_parcial_de(final: Path) -> Path:
    return final.with_name(final.stem + ".parcial.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bloque", type=int, default=25, help="Máx. puntos por bloque (2–50)")
    parser.add_argument("--pausa", type=float, default=1.0, help="Segundos entre peticiones")
    parser.add_argument("--osrm-url", default=config.OSRM_URL)
    parser.add_argument("--desde-cero", action="store_true", help="Ignorar el avance parcial guardado")
    args = parser.parse_args()
    if not 2 <= args.bloque <= BLOQUE_MAXIMO // 2:
        raise SystemExit(f"--bloque debe estar entre 2 y {BLOQUE_MAXIMO // 2}")

    from app.database import engine

    puntos = leer_puntos(engine)
    if not puntos:
        raise SystemExit("No hay puntos críticos: corre antes scripts/importar_puntos_criticos.py")

    final = archivo_cache()
    parcial = archivo_parcial_de(final)
    if args.desde_cero and parcial.exists():
        parcial.unlink()

    bloques = dividir_en_bloques(len(puntos), args.bloque)
    print(
        f"Puntos: {len(puntos)}; bloques: {[len(b) for b in bloques]}; "
        f"peticiones: hasta {len(bloques) ** 2}; servidor: {args.osrm_url}"
    )
    try:
        resultado = calcular(puntos, args.osrm_url, args.bloque, args.pausa, archivo_parcial=parcial)
        guardar(puntos, resultado.distancias_m, final, args.osrm_url, resultado.pares_aproximados)
    except ErrorOsrm as error:
        raise SystemExit(
            f"ERROR: {error}\nNo se escribió {final.name}. El avance quedó en {parcial.name}: "
            "vuelve a correr el script para reanudar."
        )
    except MatrizInvalida as error:
        raise SystemExit(f"ERROR: matriz inválida ({error}). No se escribió {final.name}.")

    parcial.unlink(missing_ok=True)
    print(f"\nMatriz {len(puntos)}×{len(puntos)} validada y guardada en {final}")
    print(f"Peticiones hechas: {resultado.peticiones}; bloques reanudados: {resultado.bloques_reanudados}")
    print(
        f"Pares sin ruta por calles (distancia aproximada haversine × "
        f"{config.OPTIMIZADOR_FACTOR_CIRCUITO}): {len(resultado.pares_aproximados)}"
    )
    for i, j in resultado.pares_aproximados[:20]:
        print(f"  - {puntos[i].codigo} -> {puntos[j].codigo}")
    if len(resultado.pares_aproximados) > 20:
        print(f"  … y {len(resultado.pares_aproximados) - 20} más (ver pares_aproximados en el archivo)")


if __name__ == "__main__":
    main()
