r"""Migración idempotente para la tabla `reportes_ciudadanos`.

`crear_tablas.py` usa `Base.metadata.create_all`, que no altera tablas que ya
existen. Este script agrega la columna `asignado_a` y amplía la restricción de
`estado` para permitir el valor intermedio `en_atencion`.

Uso:
    .\venv\Scripts\python.exe scripts\migrar_reportes.py
"""

from sqlalchemy import inspect, text

from app.database import engine


def main() -> None:
    inspector = inspect(engine)
    if "reportes_ciudadanos" not in inspector.get_table_names():
        print("La tabla reportes_ciudadanos no existe; nada que migrar.")
        return

    with engine.begin() as conexion:
        conexion.execute(
            text(
                "ALTER TABLE reportes_ciudadanos "
                "ADD COLUMN IF NOT EXISTS asignado_a VARCHAR(120)"
            )
        )
        conexion.execute(
            text(
                "ALTER TABLE reportes_ciudadanos "
                "DROP CONSTRAINT IF EXISTS ck_reportes_ciudadanos_estado"
            )
        )
        conexion.execute(
            text(
                "ALTER TABLE reportes_ciudadanos "
                "ADD CONSTRAINT ck_reportes_ciudadanos_estado "
                "CHECK (estado IN ('pendiente', 'en_atencion', 'atendido'))"
            )
        )

    print("Tabla reportes_ciudadanos migrada (asignado_a + estado en_atencion).")


if __name__ == "__main__":
    main()
