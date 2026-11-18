r"""Prepara la base para el sensor del contenedor prototipo, sin borrar datos.

Es idempotente (puede correrse varias veces):
- puntos_criticos: agrega `es_prototipo` (default false) y `nodo_id` (FK única
  y nullable a nodos);
- reportes_campo: agrega `origen` ('campo' por defecto) y `nivel_pct`, hace
  nullable `usuario_id` (los reportes de sensor no tienen usuario) y agrega los
  CHECK de origen y "usuario obligatorio si es de campo";
- crea la tabla `alertas` si no existe.
Las filas existentes quedan como antes (puntos oficiales, reportes de campo).

Uso:
    .\venv\Scripts\python.exe scripts\migrar_sensor_prototipo.py
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from sqlalchemy import text
from sqlalchemy.engine import Engine

SENTENCIAS = (
    "ALTER TABLE puntos_criticos ADD COLUMN IF NOT EXISTS es_prototipo BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE puntos_criticos ADD COLUMN IF NOT EXISTS nodo_id INTEGER REFERENCES nodos(id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS puntos_criticos_nodo_id_key ON puntos_criticos (nodo_id)",
    "ALTER TABLE reportes_campo ADD COLUMN IF NOT EXISTS origen VARCHAR NOT NULL DEFAULT 'campo'",
    "ALTER TABLE reportes_campo ADD COLUMN IF NOT EXISTS nivel_pct DOUBLE PRECISION",
    "ALTER TABLE reportes_campo ALTER COLUMN usuario_id DROP NOT NULL",
)

CHECKS = {
    "ck_reportes_campo_origen": "CHECK (origen IN ('campo', 'sensor'))",
    "ck_reportes_campo_usuario_si_campo": "CHECK (origen = 'sensor' OR usuario_id IS NOT NULL)",
}


def migrar(engine: Engine) -> None:
    from app.models.alerta import Alerta
    from app.models.nodo import Nodo
    from app.models.punto_critico import PuntoCritico
    from app.models.reporte_campo import ReporteCampo
    from app.models.usuario import Usuario

    # Crea lo que falte (ya con el esquema nuevo) antes de alterar lo existente.
    for tabla in (Nodo.__table__, Usuario.__table__, PuntoCritico.__table__, ReporteCampo.__table__):
        tabla.create(engine, checkfirst=True)

    with engine.begin() as c:
        for sentencia in SENTENCIAS:
            c.execute(text(sentencia))
        for nombre, definicion in CHECKS.items():
            existe = c.scalar(
                text("SELECT 1 FROM pg_constraint WHERE conname = :nombre"), {"nombre": nombre}
            )
            if not existe:
                c.execute(text(f"ALTER TABLE reportes_campo ADD CONSTRAINT {nombre} {definicion}"))

    Alerta.__table__.create(engine, checkfirst=True)


def main() -> None:
    from app.database import engine

    migrar(engine)
    print("puntos_criticos: es_prototipo y nodo_id al día.")
    print("reportes_campo: origen, nivel_pct y usuario_id nullable (solo para sensor) al día.")
    print("alertas: tabla al día.")


if __name__ == "__main__":
    main()
