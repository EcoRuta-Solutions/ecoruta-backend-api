r"""Carga la flota provisional de SEGAT por turnos en la tabla `camiones`.

Flota (dato de SEGAT / Municipalidad de Trujillo):
- mañana: 13 operativos + 3 en reserva (reemplazan a uno de los 13 si falla)
- tarde:  8 operativos
- noche:  13 operativos
Total: 37 registros.

No hay placas reales: se usan códigos provisionales CAM-M01…, CAM-R01…,
CAM-T01…, CAM-N01…, que no tienen el formato de una placa peruana. Todos quedan
con datos_confirmados=false. La capacidad no está confirmada: si no se pasa
--capacidad-toneladas queda NULL; si se pasa, capacidad (kg) = toneladas * 1000.

Es idempotente: si el código ya existe, no se crea de nuevo ni se cambian su
turno ni su estado (respeta los cambios hechos desde la API). Solo se actualiza
la capacidad cuando se pasa --capacidad-toneladas. No toca los camiones demo.
Antes de cargar aplica scripts/migrar_camiones_flota.py.

Uso:
    .\venv\Scripts\python.exe scripts\cargar_flota_turnos.py
    .\venv\Scripts\python.exe scripts\cargar_flota_turnos.py --capacidad-toneladas 12.5
"""

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from migrar_camiones_flota import migrar
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.turnos import Turno
from app.models.camion import Camion, EstadoCamion

# turno, estado, cantidad, prefijo del código provisional
FLOTA_PROVISIONAL = (
    (Turno.manana, EstadoCamion.operativo, 13, "CAM-M"),
    (Turno.manana, EstadoCamion.reserva, 3, "CAM-R"),
    (Turno.tarde, EstadoCamion.operativo, 8, "CAM-T"),
    (Turno.noche, EstadoCamion.operativo, 13, "CAM-N"),
)


def camiones_provisionales() -> list[tuple[str, Turno, EstadoCamion]]:
    return [
        (f"{prefijo}{numero:02d}", turno, estado)
        for turno, estado, cantidad, prefijo in FLOTA_PROVISIONAL
        for numero in range(1, cantidad + 1)
    ]


@dataclass
class ResultadoCarga:
    creados: Counter = field(default_factory=Counter)  # (turno, estado) -> n
    ya_existian: int = 0
    capacidad_actualizada: int = 0

    @property
    def total_creados(self) -> int:
        return sum(self.creados.values())


def cargar(engine: Engine, capacidad_toneladas: float | None = None) -> ResultadoCarga:
    if capacidad_toneladas is not None and capacidad_toneladas <= 0:
        raise ValueError("--capacidad-toneladas debe ser mayor que 0")

    migrar(engine)
    capacidad_kg = (
        round(capacidad_toneladas * 1000) if capacidad_toneladas is not None else None
    )
    resultado = ResultadoCarga()

    with Session(engine) as db:
        plan = camiones_provisionales()
        existentes = {
            c.placa: c
            for c in db.query(Camion).filter(Camion.placa.in_([p for p, _, _ in plan]))
        }

        for placa, turno, estado in plan:
            camion = existentes.get(placa)
            if camion is None:
                db.add(
                    Camion(
                        placa=placa,
                        turno=turno.value,
                        estado=estado.value,
                        capacidad=capacidad_kg,
                        capacidad_toneladas=capacidad_toneladas,
                        datos_confirmados=False,
                        es_demo=False,
                    )
                )
                resultado.creados[(turno.value, estado.value)] += 1
                continue

            resultado.ya_existian += 1
            if capacidad_toneladas is not None and (
                camion.capacidad_toneladas != capacidad_toneladas
                or camion.capacidad != capacidad_kg
            ):
                camion.capacidad_toneladas = capacidad_toneladas
                camion.capacidad = capacidad_kg
                resultado.capacidad_actualizada += 1

        db.commit()

    return resultado


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--capacidad-toneladas",
        type=float,
        default=None,
        help="Capacidad provisional por camión en toneladas (por defecto, sin capacidad: NULL)",
    )
    args = parser.parse_args()

    from app.database import SessionLocal, engine
    from app.services.flota_service import resumen_flota

    resultado = cargar(engine, args.capacidad_toneladas)

    print(f"Camiones creados: {resultado.total_creados}")
    for turno, estado, _, _ in FLOTA_PROVISIONAL:
        print(f"  {turno.value:<7} {estado.value:<10} {resultado.creados[(turno.value, estado.value)]}")
    print(f"Ya existían (sin cambios de turno/estado): {resultado.ya_existian}")
    if args.capacidad_toneladas is not None:
        print(f"Con capacidad actualizada: {resultado.capacidad_actualizada}")
    capacidad = (
        f"{args.capacidad_toneladas} t (provisional)"
        if args.capacidad_toneladas is not None
        else "NULL (sin confirmar)"
    )
    print(f"Capacidad cargada: {capacidad}; datos_confirmados=false")

    with SessionLocal() as db:
        resumen = resumen_flota(db)
    print(f"\nEn la tabla camiones: {resumen.total} (demo: {resumen.demo})")
    for turno, conteo in resumen.por_turno.items():
        print(
            f"  {turno.value:<7} operativo={conteo.operativo} "
            f"reserva={conteo.reserva} mantenimiento={conteo.mantenimiento}"
        )
    if resumen.sin_turno_reconocido:
        print(f"  sin turno reconocido: {resumen.sin_turno_reconocido}")


if __name__ == "__main__":
    main()
