r"""Llena conductores.camion_id cruzando por placa con la tabla vieja `vehiculos`.

Para cada conductor con vehiculo_id y sin camion_id, busca el camión con la
misma placa que su vehículo y guarda su id. No pisa un camion_id ya asignado
(por ejemplo desde la API).

No crea camiones: las placas de `vehiculos` que no existen en `camiones` solo se
REPORTAN, para que alguien las confirme y las cargue a mano.

Es idempotente. Antes aplica scripts/migrar_unificar_flota.py.

Uso:
    .\venv\Scripts\python.exe scripts\vincular_conductores_camion.py
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from migrar_unificar_flota import migrar
from sqlalchemy import text
from sqlalchemy.engine import Engine

VINCULAR = """
UPDATE conductores k SET camion_id = c.id
FROM vehiculos v JOIN camiones c ON c.placa = v.placa
WHERE k.vehiculo_id = v.id AND k.camion_id IS NULL
"""

PLACAS_SIN_PAREJA = """
SELECT v.placa FROM vehiculos v
WHERE NOT EXISTS (SELECT 1 FROM camiones c WHERE c.placa = v.placa)
ORDER BY v.placa
"""

CONDUCTORES_SIN_PAREJA = """
SELECT k.nombre, v.placa FROM conductores k JOIN vehiculos v ON v.id = k.vehiculo_id
WHERE k.camion_id IS NULL
  AND NOT EXISTS (SELECT 1 FROM camiones c WHERE c.placa = v.placa)
ORDER BY k.nombre
"""

# camion_id ya asignado que no coincide con la placa de su vehiculo_id viejo.
CONDUCTORES_DISTINTOS = """
SELECT k.nombre, v.placa, c.placa FROM conductores k
JOIN vehiculos v ON v.id = k.vehiculo_id
JOIN camiones c ON c.id = k.camion_id
WHERE c.placa <> v.placa
ORDER BY k.nombre
"""


@dataclass
class ResultadoVinculo:
    vinculados: int = 0
    placas_sin_pareja: list[str] = field(default_factory=list)
    conductores_sin_pareja: list[tuple[str, str]] = field(default_factory=list)
    conductores_distintos: list[tuple[str, str, str]] = field(default_factory=list)


def vincular(engine: Engine) -> ResultadoVinculo:
    migrar(engine)
    with engine.begin() as conexion:
        resultado = ResultadoVinculo(vinculados=conexion.execute(text(VINCULAR)).rowcount)
        resultado.placas_sin_pareja = list(conexion.scalars(text(PLACAS_SIN_PAREJA)))
        resultado.conductores_sin_pareja = [
            tuple(f) for f in conexion.execute(text(CONDUCTORES_SIN_PAREJA))
        ]
        resultado.conductores_distintos = [
            tuple(f) for f in conexion.execute(text(CONDUCTORES_DISTINTOS))
        ]
    return resultado


def main() -> None:
    from app.database import engine

    resultado = vincular(engine)
    print(f"Conductores vinculados ahora a un camión: {resultado.vinculados}")

    if resultado.placas_sin_pareja:
        print("\nPlacas de `vehiculos` SIN camión con la misma placa (no se crean solas;")
        print("confírmalas y cárgalas en camiones si son reales):")
        for placa in resultado.placas_sin_pareja:
            print(f"  - {placa}")
    else:
        print("Todas las placas de `vehiculos` tienen camión.")

    if resultado.conductores_sin_pareja:
        print("\nConductores que quedan sin camion_id por eso:")
        for nombre, placa in resultado.conductores_sin_pareja:
            print(f"  - {nombre} (vehículo {placa})")

    if resultado.conductores_distintos:
        print("\nConductores con camion_id distinto al de su vehículo viejo (no se tocan):")
        for nombre, placa_vieja, placa_camion in resultado.conductores_distintos:
            print(f"  - {nombre}: vehículo {placa_vieja}, camión {placa_camion}")


if __name__ == "__main__":
    main()
