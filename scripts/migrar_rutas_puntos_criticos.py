r"""Permite que las rutas visiten puntos críticos reales, sin borrar datos.

Es idempotente (puede correrse varias veces):
- paradas: agrega `punto_critico_id` (FK nullable a puntos_criticos, con índice),
  hace nullable `nodo_id` y agrega el CHECK "nodo_id o punto_critico_id";
- rutas: agrega `turno`, `distancia_km`, `tiempo_estimado_min` y
  `metodo_distancia` (nullable; las rutas existentes quedan en null).
Las paradas existentes conservan su nodo_id.

Uso:
    .\venv\Scripts\python.exe scripts\migrar_rutas_puntos_criticos.py
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from sqlalchemy import text
from sqlalchemy.engine import Engine

SENTENCIAS = (
    "ALTER TABLE paradas ADD COLUMN IF NOT EXISTS punto_critico_id INTEGER "
    "REFERENCES puntos_criticos(id)",
    "CREATE INDEX IF NOT EXISTS ix_paradas_punto_critico_id ON paradas (punto_critico_id)",
    "ALTER TABLE paradas ALTER COLUMN nodo_id DROP NOT NULL",
    "ALTER TABLE rutas ADD COLUMN IF NOT EXISTS turno VARCHAR",
    "ALTER TABLE rutas ADD COLUMN IF NOT EXISTS distancia_km DOUBLE PRECISION",
    "ALTER TABLE rutas ADD COLUMN IF NOT EXISTS tiempo_estimado_min DOUBLE PRECISION",
    "ALTER TABLE rutas ADD COLUMN IF NOT EXISTS metodo_distancia VARCHAR",
)

CHECK = (
    "ALTER TABLE paradas ADD CONSTRAINT ck_paradas_nodo_o_punto "
    "CHECK (nodo_id IS NOT NULL OR punto_critico_id IS NOT NULL)"
)


def migrar(engine: Engine) -> None:
    from app.models.punto_critico import PuntoCritico
    from app.models.ruta import Parada, Ruta

    # Crea lo que falte (con las columnas nuevas) antes de alterar lo existente.
    for tabla in (PuntoCritico.__table__, Ruta.__table__, Parada.__table__):
        tabla.create(engine, checkfirst=True)

    with engine.begin() as conexion:
        for sentencia in SENTENCIAS:
            conexion.execute(text(sentencia))
        existe_check = conexion.scalar(
            text(
                "SELECT 1 FROM pg_constraint "
                "WHERE conname = 'ck_paradas_nodo_o_punto'"
            )
        )
        if not existe_check:
            conexion.execute(text(CHECK))


def main() -> None:
    from app.database import engine

    migrar(engine)
    print("paradas: punto_critico_id agregado, nodo_id nullable y CHECK nodo o punto al día.")
    print("rutas: turno, distancia_km, tiempo_estimado_min y metodo_distancia al día.")


if __name__ == "__main__":
    main()
