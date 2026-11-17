r"""Borra SOLO los datos demo (filas con es_demo = true). Dry-run por defecto.

Qué borra (en este orden, dentro de una transacción):
1. paradas de rutas demo (ruta con es_demo o de un camión demo);
2. esas rutas demo;
3. camiones con es_demo;
4. nodos con es_demo y sus lecturas, salvo los que todavía usa una parada real;
5. usuarios con es_demo, salvo los que todavía usa una ruta real o un conductor.

Lo que no puede borrarse sin tocar datos reales se reporta como "bloqueado".
`vehiculos` y `conductores` no tienen es_demo: no se tocan y se listan aparte
las filas que coinciden con seed_demo.py.

Sin --aplicar ejecuta todo y hace ROLLBACK, así los números son exactos pero no
cambia nada. Si falta la columna es_demo en alguna tabla, no borra nada y pide
correr scripts/migrar_es_demo.py.

Uso:
    .\venv\Scripts\python.exe scripts\limpiar_datos_demo.py            # dry-run
    .\venv\Scripts\python.exe scripts\limpiar_datos_demo.py --aplicar  # borra
"""

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

TABLAS_CON_ES_DEMO = ("camiones", "usuarios", "rutas", "nodos")

RUTAS_DEMO = (
    "SELECT r.id FROM rutas r JOIN camiones c ON c.id = r.camion_id "
    "WHERE r.es_demo OR c.es_demo"
)
NODO_EN_USO = "EXISTS (SELECT 1 FROM paradas p WHERE p.nodo_id = n.id)"
USUARIO_EN_USO = (
    "(EXISTS (SELECT 1 FROM rutas r WHERE r.conductor_id = u.id) "
    "OR EXISTS (SELECT 1 FROM conductores k WHERE k.usuario_id = u.id))"
)

BORRADOS = (
    ("paradas", f"DELETE FROM paradas WHERE ruta_id IN ({RUTAS_DEMO})"),
    ("rutas", f"DELETE FROM rutas WHERE id IN ({RUTAS_DEMO})"),
    (
        "camiones",
        "DELETE FROM camiones c WHERE c.es_demo "
        "AND NOT EXISTS (SELECT 1 FROM rutas r WHERE r.camion_id = c.id)",
    ),
    (
        "lecturas",
        "DELETE FROM lecturas WHERE nodo_id IN "
        f"(SELECT n.id FROM nodos n WHERE n.es_demo AND NOT {NODO_EN_USO})",
    ),
    ("nodos", f"DELETE FROM nodos n WHERE n.es_demo AND NOT {NODO_EN_USO}"),
    ("usuarios", f"DELETE FROM usuarios u WHERE u.es_demo AND NOT {USUARIO_EN_USO}"),
)

# Se consultan después de borrar las rutas demo: lo que queda es real.
BLOQUEOS = {
    "camiones": (
        "SELECT c.placa FROM camiones c WHERE c.es_demo "
        "AND EXISTS (SELECT 1 FROM rutas r WHERE r.camion_id = c.id) ORDER BY c.placa"
    ),
    "nodos": (
        f"SELECT n.codigo FROM nodos n WHERE n.es_demo AND {NODO_EN_USO} "
        "ORDER BY n.codigo"
    ),
    "usuarios": (
        f"SELECT u.email FROM usuarios u WHERE u.es_demo AND {USUARIO_EN_USO} "
        "ORDER BY u.email"
    ),
}


class ColumnasFaltantes(RuntimeError):
    def __init__(self, tablas: list[str]):
        self.tablas = tablas
        super().__init__(
            "Falta la columna es_demo en: "
            + ", ".join(tablas)
            + ". Corre primero scripts/migrar_es_demo.py "
            "(ALTER TABLE <tabla> ADD COLUMN IF NOT EXISTS es_demo BOOLEAN NOT NULL "
            "DEFAULT false). No se borró nada."
        )


@dataclass
class ResultadoLimpieza:
    aplicado: bool
    borradas: dict[str, int] = field(default_factory=dict)
    bloqueadas: dict[str, list[str]] = field(default_factory=dict)
    # Filas demo de tablas sin es_demo (vehiculos, conductores): no se tocan.
    sin_es_demo: dict[str, list[str]] = field(default_factory=dict)


def columnas_faltantes(engine: Engine) -> list[str]:
    inspector = inspect(engine)
    faltan = []
    for tabla in TABLAS_CON_ES_DEMO:
        if not inspector.has_table(tabla):
            faltan.append(f"{tabla} (no existe la tabla)")
            continue
        columnas = {c["name"] for c in inspector.get_columns(tabla)}
        if "es_demo" not in columnas:
            faltan.append(tabla)
    return faltan


def _demo_sin_es_demo(conexion) -> dict[str, list[str]]:
    """Filas creadas por seed_demo.py en tablas que no tienen es_demo."""
    from seed_demo import CONDUCTORES, VEHICULOS

    placas = [placa for placa, *_ in VEHICULOS]
    nombres = [nombre for nombre, *_ in CONDUCTORES]
    return {
        "vehiculos": list(
            conexion.scalars(
                text("SELECT placa FROM vehiculos WHERE placa = ANY(:p) ORDER BY placa"),
                {"p": placas},
            )
        ),
        "conductores": list(
            conexion.scalars(
                text("SELECT nombre FROM conductores WHERE nombre = ANY(:n) ORDER BY nombre"),
                {"n": nombres},
            )
        ),
    }


def limpiar(engine: Engine, aplicar: bool = False) -> ResultadoLimpieza:
    faltan = columnas_faltantes(engine)
    if faltan:
        raise ColumnasFaltantes(faltan)

    resultado = ResultadoLimpieza(aplicado=aplicar)
    with engine.connect() as conexion:
        transaccion = conexion.begin()
        try:
            for tabla, sentencia in BORRADOS:
                resultado.borradas[tabla] = conexion.execute(text(sentencia)).rowcount
            for tabla, consulta in BLOQUEOS.items():
                resultado.bloqueadas[tabla] = list(conexion.scalars(text(consulta)))
            resultado.sin_es_demo = _demo_sin_es_demo(conexion)
        except Exception:
            transaccion.rollback()
            raise
        if aplicar:
            transaccion.commit()
        else:
            transaccion.rollback()
    return resultado


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="Borrar de verdad (sin esta opción solo muestra qué se borraría)",
    )
    args = parser.parse_args(argv)

    from app.database import engine

    try:
        resultado = limpiar(engine, aplicar=args.aplicar)
    except ColumnasFaltantes as error:
        raise SystemExit(f"ERROR: {error}")

    if resultado.aplicado:
        print("Datos demo BORRADOS:")
    else:
        print("DRY-RUN (no se borró nada). Se borrarían:")
    for tabla, cantidad in resultado.borradas.items():
        print(f"  {tabla:<9} {cantidad}")

    if any(resultado.bloqueadas.values()):
        print("\nDemo que NO se puede borrar porque lo usan datos reales:")
        for tabla, filas in resultado.bloqueadas.items():
            if filas:
                print(f"  {tabla}: {', '.join(filas)}")

    if any(resultado.sin_es_demo.values()):
        print("\nDemo sin columna es_demo (fuera de alcance, no se toca):")
        for tabla, filas in resultado.sin_es_demo.items():
            if filas:
                print(f"  {tabla}: {', '.join(filas)}")

    if not resultado.aplicado:
        print("\nPara borrar de verdad: python scripts\\limpiar_datos_demo.py --aplicar")


if __name__ == "__main__":
    main()
