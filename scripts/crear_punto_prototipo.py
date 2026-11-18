r"""Crea (o actualiza) el punto crítico del contenedor prototipo y su sensor.

- Punto crítico "PROTO-UTP", dirección "Prototipo EcoRuta (UTP)", es_prototipo = true.
  No entra en el listado oficial (151 puntos), en sus estadísticas ni en el
  reparto por turno; se ve en el mapa con GET /puntos-criticos?incluir_prototipo=true.
- Nodo/sensor "PROTO-UTP" vinculado al punto: sus lecturas (POST /sensores/lecturas)
  dan el llenado del punto.

Las coordenadas son OBLIGATORIAS (las del lugar real donde estará el contenedor);
el script no inventa ninguna. Es idempotente: si ya existen, actualiza su ubicación.

Campos que el modelo exige y que no aplican a un prototipo:
- estado = "potencial" y priorizacion_obligatoria = false (no es un punto oficial).

Uso:
    .\venv\Scripts\python.exe scripts\crear_punto_prototipo.py --lat -8.0000 --lon -79.0000
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from migrar_sensor_prototipo import migrar
from sqlalchemy import func
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.nodo import Nodo
from app.models.punto_critico import EstadoPuntoCritico, PuntoCritico

CODIGO = "PROTO-UTP"
DIRECCION = "Prototipo EcoRuta (UTP)"
NOMBRE_NODO = "Sensor prototipo EcoRuta (UTP)"
# Umbral del nodo para el panel de nodos (igual que "lleno" del sensor).
UMBRAL_CRITICO = 85

# Rango del distrito de Trujillo (mismo que el importador de puntos críticos).
LAT_MIN, LAT_MAX = -8.13, -8.08
LON_MIN, LON_MAX = -79.06, -78.99


class CoordenadaInvalida(ValueError):
    pass


@dataclass
class Resultado:
    punto: PuntoCritico
    nodo: Nodo
    punto_creado: bool
    nodo_creado: bool
    fuera_de_trujillo: bool


def validar(lat: float, lon: float) -> bool:
    """Lanza CoordenadaInvalida si no son coordenadas válidas. Devuelve True si caen fuera de Trujillo."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise CoordenadaInvalida(f"Coordenadas inválidas: lat={lat}, lon={lon}")
    return not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX)


def crear(engine: Engine, lat: float, lon: float) -> Resultado:
    fuera = validar(lat, lon)
    migrar(engine)

    with Session(engine) as db:
        nodo = db.query(Nodo).filter(Nodo.codigo == CODIGO).first()
        nodo_creado = nodo is None
        if nodo_creado:
            nodo = Nodo(codigo=CODIGO)
            db.add(nodo)
        nodo.nombre = NOMBRE_NODO
        nodo.latitud = lat
        nodo.longitud = lon
        nodo.umbral_critico = UMBRAL_CRITICO
        nodo.es_demo = False  # es un sensor real del prototipo
        db.flush()

        punto = db.query(PuntoCritico).filter(PuntoCritico.codigo_unico == CODIGO).first()
        punto_creado = punto is None
        if punto_creado:
            punto = PuntoCritico(
                codigo_unico=CODIGO,
                estado=EstadoPuntoCritico.potencial,
                priorizacion_obligatoria=False,
            )
            db.add(punto)
        punto.direccion = DIRECCION
        punto.referencia = "Contenedor con sensor ultrasónico (ESP32 + HC-SR04)"
        punto.ubicacion = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
        punto.es_prototipo = True
        punto.nodo_id = nodo.id
        db.commit()
        db.refresh(punto)
        db.refresh(nodo)
        return Resultado(punto, nodo, punto_creado, nodo_creado, fuera)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lat", type=float, required=True, help="Latitud real del contenedor (WGS84)")
    parser.add_argument("--lon", type=float, required=True, help="Longitud real del contenedor (WGS84)")
    args = parser.parse_args()

    from app.database import engine

    try:
        resultado = crear(engine, args.lat, args.lon)
    except CoordenadaInvalida as error:
        raise SystemExit(f"ERROR: {error}")

    accion = "creado" if resultado.punto_creado else "actualizado"
    print(f"Punto {CODIGO} {accion} (id {resultado.punto.id}): lat={args.lat}, lon={args.lon}")
    print(f"Nodo/sensor {CODIGO} {'creado' if resultado.nodo_creado else 'actualizado'} (id {resultado.nodo.id})")
    if resultado.fuera_de_trujillo:
        print("AVISO: las coordenadas caen fuera del rango del distrito de Trujillo; revisa lat/lon.")


if __name__ == "__main__":
    main()
