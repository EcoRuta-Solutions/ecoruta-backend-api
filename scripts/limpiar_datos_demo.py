r"""Borra SOLO los datos demo (filas con es_demo = true). Dry-run por defecto.

Qué borra (en este orden, dentro de una transacción):
1. paradas de rutas demo (ruta con es_demo o de un camión demo);
2. esas rutas demo;
3. conductores con es_demo;
4. camiones con es_demo, salvo los que usa una ruta o un conductor real;
5. vehículos con es_demo (tabla vieja), salvo los que usa un conductor real;
6. nodos con es_demo y sus lecturas, salvo los que usa una parada real;
7. usuarios con es_demo, salvo los que usa una ruta o un conductor real
   (conductor@ecoruta.com se libera al borrarse su conductor demo).

Lo que no puede borrarse sin tocar datos reales se reporta como "bloqueado".

Sin --aplicar ejecuta todo y hace ROLLBACK, así los números son exactos pero no
cambia nada. Si falta alguna columna (es_demo, conductores.camion_id), no borra
nada y pide correr scripts/migrar_unificar_flota.py.

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

COLUMNAS_REQUERIDAS = {
    "camiones": ("es_demo",),
    "usuarios": ("es_demo",),
    "rutas": ("es_demo",),
    "nodos": ("es_demo",),
    "vehiculos": ("es_demo",),
    "conductores": ("es_demo", "camion_id"),
}

RUTAS_DEMO = (
    "SELECT r.id FROM rutas r JOIN camiones c ON c.id = r.camion_id "
    "WHERE r.es_demo OR c.es_demo"
)
CAMION_EN_USO = (
    "(EXISTS (SELECT 1 FROM rutas r WHERE r.camion_id = c.id) "
    "OR EXISTS (SELECT 1 FROM conductores k WHERE k.camion_id = c.id))"
)
VEHICULO_EN_USO = "EXISTS (SELECT 1 FROM conductores k WHERE k.vehiculo_id = v.id)"
NODO_EN_USO = "EXISTS (SELECT 1 FROM paradas p WHERE p.nodo_id = n.id)"
USUARIO_EN_USO = (
    "(EXISTS (SELECT 1 FROM rutas r WHERE r.conductor_id = u.id) "
    "OR EXISTS (SELECT 1 FROM conductores k WHERE k.usuario_id = u.id))"
)

BORRADOS = (
    ("paradas", f"DELETE FROM paradas WHERE ruta_id IN ({RUTAS_DEMO})"),
    ("rutas", f"DELETE FROM rutas WHERE id IN ({RUTAS_DEMO})"),
    ("conductores", "DELETE FROM conductores WHERE es_demo"),
    ("camiones", f"DELETE FROM camiones c WHERE c.es_demo AND NOT {CAMION_EN_USO}"),
    ("vehiculos", f"DELETE FROM vehiculos v WHERE v.es_demo AND NOT {VEHICULO_EN_USO}"),
    (
        "lecturas",
        "DELETE FROM lecturas WHERE nodo_id IN "
        f"(SELECT n.id FROM nodos n WHERE n.es_demo AND NOT {NODO_EN_USO})",
    ),
    ("nodos", f"DELETE FROM nodos n WHERE n.es_demo AND NOT {NODO_EN_USO}"),
    ("usuarios", f"DELETE FROM usuarios u WHERE u.es_demo AND NOT {USUARIO_EN_USO}"),
)

# Se consultan después de los borrados: lo que todavía las usa es real.
BLOQUEOS = {
    "camiones": f"SELECT c.placa FROM camiones c WHERE c.es_demo AND {CAMION_EN_USO} ORDER BY c.placa",
    "vehiculos": f"SELECT v.placa FROM vehiculos v WHERE v.es_demo AND {VEHICULO_EN_USO} ORDER BY v.placa",
    "nodos": f"SELECT n.codigo FROM nodos n WHERE n.es_demo AND {NODO_EN_USO} ORDER BY n.codigo",
    "usuarios": f"SELECT u.email FROM usuarios u WHERE u.es_demo AND {USUARIO_EN_USO} ORDER BY u.email",
}


class ColumnasFaltantes(RuntimeError):
    def __init__(self, faltantes: list[str]):
        self.faltantes = faltantes
        super().__init__(
            "Faltan columnas: "
            + ", ".join(faltantes)
            + ". Corre primero scripts/migrar_unificar_flota.py (agrega es_demo y "
            "conductores.camion_id con ADD COLUMN IF NOT EXISTS). No se borró nada."
        )


@dataclass
class ResultadoLimpieza:
    aplicado: bool
    borradas: dict[str, int] = field(default_factory=dict)
    bloqueadas: dict[str, list[str]] = field(default_factory=dict)


def columnas_faltantes(engine: Engine) -> list[str]:
    inspector = inspect(engine)
    faltan = []
    for tabla, requeridas in COLUMNAS_REQUERIDAS.items():
        if not inspector.has_table(tabla):
            faltan.append(f"{tabla} (no existe la tabla)")
            continue
        columnas = {c["name"] for c in inspector.get_columns(tabla)}
        faltan.extend(f"{tabla}.{c}" for c in requeridas if c not in columnas)
    return faltan


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
        print(f"  {tabla:<11} {cantidad}")

    if any(resultado.bloqueadas.values()):
        print("\nDemo que NO se puede borrar porque lo usan datos reales:")
        for tabla, filas in resultado.bloqueadas.items():
            if filas:
                print(f"  {tabla}: {', '.join(filas)}")

    if not resultado.aplicado:
        print("\nPara borrar de verdad: python scripts\\limpiar_datos_demo.py --aplicar")


if __name__ == "__main__":
    main()
