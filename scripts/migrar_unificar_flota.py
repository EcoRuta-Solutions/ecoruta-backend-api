r"""Prepara la unificación Camion/Vehiculo (`camiones` es la tabla principal), sin borrar datos.

Es idempotente (puede correrse varias veces):
- aplica antes scripts/migrar_es_demo.py (y con él migrar_camiones_flota.py);
- camiones: agrega `tipo` (null = por confirmar) y `activo` (default true) y
  quita el NOT NULL de `turno` (null = por confirmar);
- conductores: agrega `camion_id` (FK nullable a camiones) y `es_demo`;
- vehiculos: agrega `es_demo` y quita el NOT NULL y el default de
  `capacidad_toneladas` (el 8 era inventado). No cambia filas existentes;
- marca es_demo = true SOLO en los vehículos TCA-241, TCA-508, TCA-316 y en los
  conductores Luis Rodríguez, María Flores y José Castillo (los de seed_demo.py).

Uso:
    .\venv\Scripts\python.exe scripts\migrar_unificar_flota.py
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from migrar_camiones_flota import PLACAS_DEMO
from migrar_es_demo import migrar as migrar_es_demo
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

# Conductores de seed_demo.py.
NOMBRES_CONDUCTORES_DEMO = ("Luis Rodríguez", "María Flores", "José Castillo")

SENTENCIAS = {
    "camiones": (
        "ALTER TABLE camiones ADD COLUMN IF NOT EXISTS tipo VARCHAR",
        "ALTER TABLE camiones ADD COLUMN IF NOT EXISTS activo BOOLEAN NOT NULL DEFAULT true",
        "ALTER TABLE camiones ALTER COLUMN turno DROP NOT NULL",
    ),
    "vehiculos": (
        "ALTER TABLE vehiculos ADD COLUMN IF NOT EXISTS es_demo BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE vehiculos ALTER COLUMN capacidad_toneladas DROP NOT NULL",
        "ALTER TABLE vehiculos ALTER COLUMN capacidad_toneladas DROP DEFAULT",
    ),
    "conductores": (
        "ALTER TABLE conductores ADD COLUMN IF NOT EXISTS camion_id INTEGER "
        "REFERENCES camiones(id)",
        "CREATE INDEX IF NOT EXISTS ix_conductores_camion_id ON conductores (camion_id)",
        "ALTER TABLE conductores ADD COLUMN IF NOT EXISTS es_demo BOOLEAN NOT NULL DEFAULT false",
    ),
}

MARCAS = {
    "vehiculos": (
        "UPDATE vehiculos SET es_demo = true WHERE placa = ANY(:valores) AND es_demo = false",
        PLACAS_DEMO,
    ),
    "conductores": (
        "UPDATE conductores SET es_demo = true WHERE nombre = ANY(:valores) AND es_demo = false",
        NOMBRES_CONDUCTORES_DEMO,
    ),
}


def migrar(engine: Engine) -> dict[str, int]:
    """Aplica los cambios y devuelve cuántas filas quedaron marcadas como demo ahora."""
    migrar_es_demo(engine)  # crea camiones si falta
    existentes = set(inspect(engine).get_table_names())
    marcadas = {}
    with engine.begin() as conexion:
        for tabla, sentencias in SENTENCIAS.items():
            if tabla not in existentes:
                continue  # crear_tablas.py la creará ya con las columnas nuevas
            for sentencia in sentencias:
                conexion.execute(text(sentencia))
        for tabla, (sentencia, valores) in MARCAS.items():
            if tabla in existentes:
                marcadas[tabla] = conexion.execute(
                    text(sentencia), {"valores": list(valores)}
                ).rowcount
    return marcadas


def main() -> None:
    from app.database import engine

    marcadas = migrar(engine)
    print("camiones: tipo, activo y turno nullable al día.")
    print("conductores: camion_id y es_demo al día.")
    print("vehiculos: es_demo al día; capacidad_toneladas nullable y sin default.")
    for tabla in MARCAS:
        print(f"  {tabla:<11} marcados ahora como demo: {marcadas.get(tabla, 0)}")


if __name__ == "__main__":
    main()
