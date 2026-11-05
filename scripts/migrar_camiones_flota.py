r"""Agrega a `camiones` las columnas de flota por turnos, sin borrar datos.

Es idempotente (puede correrse varias veces):
- agrega `capacidad_toneladas`, `estado`, `datos_confirmados` y `es_demo` si faltan;
- quita el NOT NULL de `capacidad` (la capacidad real aún no está confirmada);
- marca `es_demo = true` en los camiones demo de seed_demo.py (por placa).

Las filas existentes quedan con estado 'operativo' y datos_confirmados=false.

Uso:
    .\venv\Scripts\python.exe scripts\migrar_camiones_flota.py
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from sqlalchemy import text
from sqlalchemy.engine import Engine

# Placas de CAMIONES en seed_demo.py.
PLACAS_DEMO = ("TCA-241", "TCA-508", "TCA-316")

SENTENCIAS = (
    "ALTER TABLE camiones ADD COLUMN IF NOT EXISTS capacidad_toneladas DOUBLE PRECISION",
    "ALTER TABLE camiones ADD COLUMN IF NOT EXISTS estado VARCHAR NOT NULL DEFAULT 'operativo'",
    "ALTER TABLE camiones ADD COLUMN IF NOT EXISTS datos_confirmados BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE camiones ADD COLUMN IF NOT EXISTS es_demo BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE camiones ALTER COLUMN capacidad DROP NOT NULL",
)


def migrar(engine: Engine) -> int:
    """Aplica los cambios y devuelve cuántos camiones demo quedaron marcados ahora."""
    from app.models.camion import Camion

    Camion.__table__.create(engine, checkfirst=True)
    with engine.begin() as conexion:
        for sentencia in SENTENCIAS:
            conexion.execute(text(sentencia))
        marcados = conexion.execute(
            text(
                "UPDATE camiones SET es_demo = true "
                "WHERE placa = ANY(:placas) AND es_demo = false"
            ),
            {"placas": list(PLACAS_DEMO)},
        ).rowcount
    return marcados


def main() -> None:
    from app.database import engine

    marcados = migrar(engine)
    print("Columnas de camiones al día (capacidad_toneladas, estado, datos_confirmados, es_demo).")
    print("capacidad (kg) ahora admite NULL.")
    print(f"Camiones demo marcados ahora: {marcados}")


if __name__ == "__main__":
    main()
