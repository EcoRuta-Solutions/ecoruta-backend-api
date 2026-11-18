r"""zonas_ruta pasa a tener una fila por TRAMO: único por (codigo, tramo). Sin borrar datos.

Es idempotente (puede correrse varias veces):
- quita la unicidad solo por `codigo` (índice único ix_zonas_ruta_codigo o
  restricción única sobre codigo) y deja un índice normal por codigo;
- deja `tramo` = 1 en las filas existentes que no lo tengan (null o vacío);
- convierte `tramo` a INTEGER NOT NULL (si algún valor no es un entero, se
  detiene sin cambiar nada y lista esas filas);
- agrega la restricción única uq_zonas_ruta_codigo_tramo (codigo, tramo).

Uso:
    .\venv\Scripts\python.exe scripts\migrar_zonas_ruta_tramos.py
"""

import sys
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

RESTRICCION = "uq_zonas_ruta_codigo_tramo"
INDICE_CODIGO = "ix_zonas_ruta_codigo"


class TramosInvalidos(RuntimeError):
    pass


@dataclass
class ResultadoMigracion:
    tramos_completados: int = 0
    unicidad_codigo_quitada: bool = False
    tramo_convertido: bool = False
    restriccion_agregada: bool = False


def migrar(engine: Engine) -> ResultadoMigracion:
    from app.models.zona_ruta import ZonaRuta

    resultado = ResultadoMigracion()
    if not inspect(engine).has_table("zonas_ruta"):
        ZonaRuta.__table__.create(engine)  # base nueva: ya nace con el esquema final
        return resultado

    with engine.begin() as c:
        tipo = c.scalar(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'zonas_ruta' AND column_name = 'tramo'"
            )
        )
        if tipo is None:
            c.execute(text("ALTER TABLE zonas_ruta ADD COLUMN tramo INTEGER"))
            tipo = "integer"

        if tipo != "integer":
            invalidos = c.execute(
                text(
                    "SELECT codigo, tramo FROM zonas_ruta "
                    "WHERE NULLIF(trim(tramo), '') IS NOT NULL AND trim(tramo) !~ '^[0-9]+$' "
                    "ORDER BY codigo"
                )
            ).all()
            if invalidos:
                raise TramosInvalidos(
                    "Hay tramos que no son enteros; corrígelos antes de migrar: "
                    + ", ".join(f"{codigo}={tramo!r}" for codigo, tramo in invalidos)
                )
            resultado.tramos_completados = c.execute(
                text("UPDATE zonas_ruta SET tramo = '1' WHERE NULLIF(trim(tramo), '') IS NULL")
            ).rowcount
            c.execute(
                text("ALTER TABLE zonas_ruta ALTER COLUMN tramo TYPE INTEGER USING trim(tramo)::integer")
            )
            resultado.tramo_convertido = True
        else:
            resultado.tramos_completados = c.execute(
                text("UPDATE zonas_ruta SET tramo = 1 WHERE tramo IS NULL")
            ).rowcount
        c.execute(text("ALTER TABLE zonas_ruta ALTER COLUMN tramo SET NOT NULL"))

        # Unicidad vieja solo por codigo: índice único y/o restricción única.
        indice_unico = c.scalar(
            text(
                "SELECT 1 FROM pg_indexes WHERE tablename = 'zonas_ruta' "
                "AND indexname = :nombre AND indexdef ILIKE 'CREATE UNIQUE%'"
            ),
            {"nombre": INDICE_CODIGO},
        )
        if indice_unico:
            c.execute(text(f"DROP INDEX {INDICE_CODIGO}"))
            resultado.unicidad_codigo_quitada = True
        restricciones_codigo = c.scalars(
            text(
                "SELECT con.conname FROM pg_constraint con "
                "JOIN pg_class rel ON rel.oid = con.conrelid "
                "WHERE rel.relname = 'zonas_ruta' AND con.contype = 'u' "
                "AND con.conkey = ARRAY[(SELECT attnum FROM pg_attribute "
                "  WHERE attrelid = rel.oid AND attname = 'codigo')]::smallint[]"
            )
        ).all()
        for nombre in restricciones_codigo:
            c.execute(text(f'ALTER TABLE zonas_ruta DROP CONSTRAINT "{nombre}"'))
            resultado.unicidad_codigo_quitada = True
        c.execute(text(f"CREATE INDEX IF NOT EXISTS {INDICE_CODIGO} ON zonas_ruta (codigo)"))

        existe = c.scalar(
            text("SELECT 1 FROM pg_constraint WHERE conname = :nombre"), {"nombre": RESTRICCION}
        )
        if not existe:
            c.execute(
                text(f"ALTER TABLE zonas_ruta ADD CONSTRAINT {RESTRICCION} UNIQUE (codigo, tramo)")
            )
            resultado.restriccion_agregada = True
    return resultado


def main() -> None:
    from app.database import engine

    try:
        resultado = migrar(engine)
    except TramosInvalidos as error:
        raise SystemExit(f"ERROR: {error}. No se cambió nada.")
    print("zonas_ruta: una fila por tramo, única por (codigo, tramo).")
    print(f"  tramo convertido a entero ahora: {'sí' if resultado.tramo_convertido else 'no (ya estaba)'}")
    print(f"  filas sin tramo que quedaron con tramo 1: {resultado.tramos_completados}")
    print(f"  unicidad solo por codigo quitada ahora: {'sí' if resultado.unicidad_codigo_quitada else 'no (ya estaba)'}")
    print(f"  restricción (codigo, tramo) agregada ahora: {'sí' if resultado.restriccion_agregada else 'no (ya estaba)'}")


if __name__ == "__main__":
    main()
