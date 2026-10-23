r"""Migración para retirar el rol `ciudadano`.

Las denuncias ciudadanas las atiende Alerta SEGAT, así que EcoRuta queda solo
con los roles `municipalidad` y `conductor`. Este script, en una sola
transacción:

1. Elimina la tabla `reportes_ciudadanos` (y sus filas).
2. Elimina las cuentas demo de rol `ciudadano` listadas en `CUENTAS_DEMO`.

Sin `--confirmar` solo muestra lo que haría. Saca un respaldo antes de
ejecutarlo de verdad.

Uso:
    .\venv\Scripts\python.exe scripts\eliminar_reportes_ciudadanos.py
    .\venv\Scripts\python.exe scripts\eliminar_reportes_ciudadanos.py --confirmar
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import bindparam, inspect, text

from app.database import engine

CUENTAS_DEMO = (
    "ciudadano@ecoruta.test",
    "ciudadano2@ecoruta.com",
    "user@example.com",
)

BORRAR_CUENTAS = text(
    "DELETE FROM usuarios WHERE rol = 'ciudadano' AND email IN :emails"
).bindparams(bindparam("emails", expanding=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--confirmar", action="store_true", help="ejecuta los cambios"
    )
    args = parser.parse_args()

    existe_tabla = "reportes_ciudadanos" in inspect(engine).get_table_names()

    with engine.begin() as conexion:
        reportes = (
            conexion.execute(
                text("SELECT count(*) FROM reportes_ciudadanos")
            ).scalar()
            if existe_tabla
            else 0
        )
        cuentas = conexion.execute(
            text(
                "SELECT id, email FROM usuarios "
                "WHERE rol = 'ciudadano' AND email IN :emails ORDER BY id"
            ).bindparams(bindparam("emails", expanding=True)),
            {"emails": list(CUENTAS_DEMO)},
        ).all()

        if existe_tabla:
            print(f"Tabla reportes_ciudadanos: existe, {reportes} reporte(s).")
        else:
            print("Tabla reportes_ciudadanos: no existe.")
        print(f"Cuentas demo ciudadano a borrar: {len(cuentas)}")
        for id_, email in cuentas:
            print(f"  - id {id_}: {email}")

        if not args.confirmar:
            print("\nSimulación: no se cambió nada. Usa --confirmar para ejecutar.")
            return

        # La tabla va primero: su FK usuario_id impediría borrar las cuentas.
        conexion.execute(text("DROP TABLE IF EXISTS reportes_ciudadanos"))
        borradas = conexion.execute(
            BORRAR_CUENTAS, {"emails": list(CUENTAS_DEMO)}
        ).rowcount

        restantes = conexion.execute(
            text("SELECT count(*) FROM usuarios WHERE rol = 'ciudadano'")
        ).scalar()

    print("\nTabla reportes_ciudadanos eliminada.")
    print(f"Cuentas ciudadano borradas: {borradas}")
    if restantes:
        print(
            f"Atención: quedan {restantes} usuario(s) con rol ciudadano que no "
            "están en CUENTAS_DEMO; revísalos a mano."
        )


if __name__ == "__main__":
    main()
