r"""Importa las rutas de recolección por zona de Trujillo (tabla `zonas_ruta`).

Lee `data/rutas_zona_trujillo.csv` con las columnas:
    ruta, turno, tramo, sectores, recojo_inicio, recojo_fin,
    sacar_basura_inicio, sacar_basura_fin
y una columna opcional `revisar` (true/false, si/no, 1/0) para marcar datos dudosos.

- Horas en formato 24 h (HH:MM). "24:00" se guarda como 00:00 (medianoche).
- `turno` acepta manana/mañana/tarde/noche y se guarda como manana|tarde|noche.
- `cruza_medianoche` se calcula: el recojo termina después de la medianoche
  (recojo_fin < recojo_inicio y recojo_fin distinto de 00:00).
- `revisar` queda en true si el CSV lo pide o si el código está en
  CODIGOS_REVISAR (N-9: el listado impreso tiene un hueco 23:00–24:00; se
  importa tal cual).
- Las filas inválidas se reportan y se saltan; no detienen la importación.
- No inventa datos: tramo, sectores y el horario para sacar la basura quedan
  vacíos si el CSV no los trae.

Es idempotente: actualiza por código de ruta. Crea la tabla si no existe.

Uso:
    .\venv\Scripts\python.exe scripts\importar_rutas_zona.py
    .\venv\Scripts\python.exe scripts\importar_rutas_zona.py --archivo otro.csv
"""

import argparse
import csv
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from sqlalchemy import func, literal_column, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from app.core.turnos import Turno, normalizar_turno
from app.models.zona_ruta import ZonaRuta

ARCHIVO_POR_DEFECTO = RAIZ / "data" / "rutas_zona_trujillo.csv"

COLUMNAS_CSV = (
    "ruta",
    "turno",
    "tramo",
    "sectores",
    "recojo_inicio",
    "recojo_fin",
    "sacar_basura_inicio",
    "sacar_basura_fin",
)
COLUMNA_OPCIONAL_REVISAR = "revisar"

# Rutas con datos dudosos en el listado impreso, aunque el CSV no las marque.
# N-9: hueco 23:00–24:00 tal como está impreso.
CODIGOS_REVISAR = frozenset({"N-9"})

PATRON_HORA = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
MEDIANOCHE = time(0, 0)
VALORES_BOOL = {
    "": False,
    "false": False, "no": False, "0": False,
    "true": True, "si": True, "sí": True, "1": True,
}

CAMPOS_ACTUALIZABLES = (
    "turno",
    "tramo",
    "sectores",
    "recojo_inicio",
    "recojo_fin",
    "sacar_basura_inicio",
    "sacar_basura_fin",
    "cruza_medianoche",
    "revisar",
)


class ArchivoNoEncontrado(FileNotFoundError):
    pass


@dataclass
class FilaRechazada:
    linea: int
    codigo: str
    motivo: str


@dataclass
class LecturaCsv:
    validas: list[dict] = field(default_factory=list)
    rechazadas: list[FilaRechazada] = field(default_factory=list)

    @property
    def leidas(self) -> int:
        return len(self.validas) + len(self.rechazadas)


@dataclass
class ResultadoImportacion:
    leidas: int
    creadas: int
    actualizadas: int
    sin_cambios: int
    rechazadas: list[FilaRechazada]
    total: int
    por_turno: dict[str, int]
    revisar: int


def parsear_hora(valor: str | None, nombre: str, obligatoria: bool) -> time | None:
    texto = (valor or "").strip()
    if not texto:
        if obligatoria:
            raise ValueError(f"{nombre} vacío")
        return None
    coincidencia = PATRON_HORA.match(texto)
    if not coincidencia:
        raise ValueError(f"{nombre} no tiene formato HH:MM: {valor!r}")
    horas, minutos = int(coincidencia.group(1)), int(coincidencia.group(2))
    segundos = int(coincidencia.group(3) or 0)
    if (horas, minutos, segundos) == (24, 0, 0):
        return MEDIANOCHE
    if horas > 23 or minutos > 59 or segundos > 59:
        raise ValueError(f"{nombre} fuera de rango: {valor!r}")
    return time(horas, minutos, segundos)


def cruza_medianoche(inicio: time, fin: time) -> bool:
    """True si el tramo termina al día siguiente (terminar justo a las 00:00 no cuenta)."""
    return fin != MEDIANOCHE and fin < inicio


def parsear_revisar(valor: str | None) -> bool:
    texto = (valor or "").strip().lower()
    if texto not in VALORES_BOOL:
        raise ValueError(f"revisar inválido: {valor!r} (usa true/false)")
    return VALORES_BOOL[texto]


def validar_fila(fila: dict) -> dict:
    """Devuelve los datos listos para guardar o lanza ValueError con el motivo."""
    codigo = (fila.get("ruta") or "").strip().upper()
    if not codigo:
        raise ValueError("ruta vacía")

    turno = normalizar_turno(fila.get("turno"))
    if turno is None:
        raise ValueError(f"turno inválido: {fila.get('turno')!r}")

    recojo_inicio = parsear_hora(fila.get("recojo_inicio"), "recojo_inicio", True)
    recojo_fin = parsear_hora(fila.get("recojo_fin"), "recojo_fin", True)
    sacar_inicio = parsear_hora(fila.get("sacar_basura_inicio"), "sacar_basura_inicio", False)
    sacar_fin = parsear_hora(fila.get("sacar_basura_fin"), "sacar_basura_fin", False)
    if (sacar_inicio is None) != (sacar_fin is None):
        raise ValueError("sacar_basura_inicio y sacar_basura_fin deben venir juntos")

    revisar = parsear_revisar(fila.get(COLUMNA_OPCIONAL_REVISAR))

    return {
        "codigo": codigo,
        "turno": turno.value,
        "tramo": (fila.get("tramo") or "").strip() or None,
        "sectores": (fila.get("sectores") or "").strip() or None,
        "recojo_inicio": recojo_inicio,
        "recojo_fin": recojo_fin,
        "sacar_basura_inicio": sacar_inicio,
        "sacar_basura_fin": sacar_fin,
        "cruza_medianoche": cruza_medianoche(recojo_inicio, recojo_fin),
        "revisar": revisar or codigo in CODIGOS_REVISAR,
    }


def leer_csv(ruta: Path) -> LecturaCsv:
    ruta = Path(ruta)
    if not ruta.is_file():
        raise ArchivoNoEncontrado(
            f"No existe el archivo {ruta}. Agrega el listado oficial en "
            f"data/rutas_zona_trujillo.csv o indica otro con --archivo."
        )

    lectura = LecturaCsv()
    codigos_vistos: set[str] = set()

    with open(ruta, encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo)
        faltantes = [c for c in COLUMNAS_CSV if c not in (lector.fieldnames or [])]
        if faltantes:
            raise ValueError(f"Faltan columnas en el CSV: {', '.join(faltantes)}")

        for fila in lector:
            codigo = (fila.get("ruta") or "").strip().upper()
            try:
                datos = validar_fila(fila)
                if codigo in codigos_vistos:
                    raise ValueError("ruta repetida en el archivo")
            except ValueError as error:
                lectura.rechazadas.append(
                    FilaRechazada(lector.line_num, codigo, str(error))
                )
                continue
            codigos_vistos.add(codigo)
            lectura.validas.append(datos)

    return lectura


def guardar(engine: Engine, filas: list[dict]) -> tuple[int, int]:
    """Inserta o actualiza por código. Devuelve (creadas, actualizadas)."""
    if not filas:
        return 0, 0

    tabla = ZonaRuta.__table__
    sentencia = insert(ZonaRuta).values(filas)
    nuevos = sentencia.excluded
    sentencia = sentencia.on_conflict_do_update(
        index_elements=[tabla.c.codigo],
        set_={c: nuevos[c] for c in CAMPOS_ACTUALIZABLES},
        # Solo reescribe filas que cambiaron, para distinguir "sin cambios".
        where=tuple_(*(tabla.c[c] for c in CAMPOS_ACTUALIZABLES)).is_distinct_from(
            tuple_(*(nuevos[c] for c in CAMPOS_ACTUALIZABLES))
        ),
    ).returning(literal_column("xmax = 0"))  # xmax = 0: fila recién insertada

    with engine.begin() as conexion:
        insertadas = conexion.execute(sentencia).scalars().all()

    creadas = sum(1 for nueva in insertadas if nueva)
    return creadas, len(insertadas) - creadas


def contar(engine: Engine) -> tuple[dict[str, int], int]:
    with engine.connect() as conexion:
        por_turno = Counter(
            dict(
                conexion.execute(
                    select(ZonaRuta.turno, func.count()).group_by(ZonaRuta.turno)
                ).all()
            )
        )
        revisar = conexion.scalar(
            select(func.count()).select_from(ZonaRuta).where(ZonaRuta.revisar)
        )
    return {t.value: por_turno[t.value] for t in Turno}, revisar


def importar(engine: Engine, ruta: Path) -> ResultadoImportacion:
    lectura = leer_csv(ruta)  # falla antes de tocar la base si no hay archivo
    ZonaRuta.__table__.create(engine, checkfirst=True)

    creadas, actualizadas = guardar(engine, lectura.validas)
    por_turno, revisar = contar(engine)

    return ResultadoImportacion(
        leidas=lectura.leidas,
        creadas=creadas,
        actualizadas=actualizadas,
        sin_cambios=len(lectura.validas) - creadas - actualizadas,
        rechazadas=lectura.rechazadas,
        total=sum(por_turno.values()),
        por_turno=por_turno,
        revisar=revisar,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--archivo",
        type=Path,
        default=ARCHIVO_POR_DEFECTO,
        help="CSV a importar (por defecto, data/rutas_zona_trujillo.csv)",
    )
    args = parser.parse_args()

    from app.database import engine

    try:
        resultado = importar(engine, args.archivo)
    except (ArchivoNoEncontrado, ValueError) as error:
        raise SystemExit(f"ERROR: {error}")

    print(f"Archivo: {args.archivo}")
    print(f"Filas leídas:      {resultado.leidas}")
    print(f"Creadas:           {resultado.creadas}")
    print(f"Actualizadas:      {resultado.actualizadas}")
    print(f"Sin cambios:       {resultado.sin_cambios}")
    print(f"Rechazadas:        {len(resultado.rechazadas)}")
    for rechazada in resultado.rechazadas:
        print(
            f"  - línea {rechazada.linea} ({rechazada.codigo or 'sin código'}): "
            f"{rechazada.motivo}"
        )

    print(f"\nEn la tabla zonas_ruta: {resultado.total}")
    print("Por turno:")
    for turno, cantidad in resultado.por_turno.items():
        print(f"  {turno}: {cantidad}")
    print(f"Por revisar (revisar=true): {resultado.revisar}")


if __name__ == "__main__":
    main()
