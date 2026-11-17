r"""Agrega `es_demo` a usuarios, rutas y nodos y marca lo que es demo, sin borrar datos.

Es idempotente (puede correrse varias veces):
- aplica antes scripts/migrar_camiones_flota.py (camiones.es_demo);
- agrega `es_demo BOOLEAN NOT NULL DEFAULT false` a usuarios, rutas y nodos si falta;
- marca es_demo = true SOLO en:
  - usuarios: las cuentas de scripts/crear_usuarios_demo.py (por email);
  - rutas: las que usan un camión demo;
  - nodos: TRU-001..TRU-008 de seed_demo.py (por código).
Las paradas no llevan columna: son demo las de una ruta demo.
`vehiculos` y `conductores` quedan fuera (no tienen es_demo).

Uso:
    .\venv\Scripts\python.exe scripts\migrar_es_demo.py
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from migrar_camiones_flota import migrar as migrar_camiones
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

# Cuentas de scripts/crear_usuarios_demo.py.
EMAILS_DEMO = ("conductor@ecoruta.com", "municipalidad3@ecoruta.com")
# Códigos de NODOS en seed_demo.py.
CODIGOS_NODOS_DEMO = tuple(f"TRU-{n:03d}" for n in range(1, 9))

TABLAS = ("usuarios", "rutas", "nodos")

MARCAS = {
    "usuarios": (
        "UPDATE usuarios SET es_demo = true "
        "WHERE email = ANY(:emails) AND es_demo = false"
    ),
    "rutas": (
        "UPDATE rutas r SET es_demo = true FROM camiones c "
        "WHERE c.id = r.camion_id AND c.es_demo AND r.es_demo = false"
    ),
    "nodos": (
        "UPDATE nodos SET es_demo = true "
        "WHERE codigo = ANY(:codigos) AND es_demo = false"
    ),
}


def migrar(engine: Engine) -> dict[str, int]:
    """Aplica los cambios y devuelve cuántas filas quedaron marcadas ahora, por tabla."""
    migrar_camiones(engine)
    existentes = set(inspect(engine).get_table_names())
    marcadas = {}
    with engine.begin() as conexion:
        for tabla in TABLAS:
            if tabla not in existentes:
                continue  # crear_tablas.py la creará ya con la columna
            conexion.execute(
                text(
                    f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS "
                    "es_demo BOOLEAN NOT NULL DEFAULT false"
                )
            )
        parametros = {
            "usuarios": {"emails": list(EMAILS_DEMO)},
            "rutas": {},
            "nodos": {"codigos": list(CODIGOS_NODOS_DEMO)},
        }
        for tabla in TABLAS:
            if tabla not in existentes:
                continue
            marcadas[tabla] = conexion.execute(
                text(MARCAS[tabla]), parametros[tabla]
            ).rowcount
    return marcadas


def main() -> None:
    from app.database import engine

    marcadas = migrar(engine)
    print("Columna es_demo al día en camiones, usuarios, rutas y nodos.")
    for tabla in TABLAS:
        print(f"  {tabla:<9} marcadas ahora como demo: {marcadas.get(tabla, 0)}")


if __name__ == "__main__":
    main()
