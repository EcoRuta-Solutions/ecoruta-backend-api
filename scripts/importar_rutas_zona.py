r"""Importa las rutas de recolección por zona de Trujillo (tabla `zonas_ruta`).

Lee `data/rutas_zona_trujillo.csv`, con UNA FILA POR TRAMO y las columnas:
    ruta, turno, tramo, sectores, recojo_inicio, recojo_fin,
    sacar_basura_inicio, sacar_basura_fin
y una columna opcional `revisar` (true/false, si/no, 1/0) para marcar datos dudosos.

- `tramo` es un entero >= 1. Cada (ruta, tramo) es una fila; repetir el mismo
  (ruta, tramo) en el archivo se rechaza. Todos los tramos de una ruta deben
  tener el mismo turno.
- Horas en formato 24 h (HH:MM). "24:00" se guarda como 00:00 (medianoche).
- `turno` acepta manana/mañana/tarde/noche y se guarda como manana|tarde|noche.
- `cruza_medianoche` se calcula: el recojo termina después de la medianoche
  (recojo_fin < recojo_inicio y recojo_fin distinto de 00:00).
- `revisar` queda en true si esa fila lo pide en el CSV o si el código está en
  CODIGOS_REVISAR (N-9, en todos sus tramos: el listado impreso tiene un hueco
  23:00–24:00; se importa tal cual).
- Las filas inválidas se reportan y se saltan; no detienen la importación.
- No inventa datos: sectores y el horario para sacar la basura quedan vacíos si
  el CSV no los trae.

Es idempotente: actualiza por (ruta, tramo). Antes aplica
scripts/migrar_zonas_ruta_tramos.py (crea la tabla si no existe).

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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import func, literal_column, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from migrar_zonas_ruta_tramos import TramosInvalidos
from migrar_zonas_ruta_tramos import migrar as migrar_tramos

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
    total_tramos: int
    total_rutas: int
    # Rutas distintas por turno (cuenta rutas, no tramos).
    rutas_por_turno: dict[str, int]
    tramos_por_revisar: int


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


def parsear_tramo(valor: str | None) -> int:
    texto = (valor or "").strip()
    if not texto:
        raise ValueError("tramo vacío")
    if not texto.isdigit() or int(texto) < 1:
        raise ValueError(f"tramo debe ser un entero >= 1: {valor!r}")
    return int(texto)


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
        "tramo": parsear_tramo(fila.get("tramo")),
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
    claves_vistas: set[tuple[str, int]] = set()
    turno_de_ruta: dict[str, str] = {}

    with open(ruta, encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo)
        faltantes = [c for c in COLUMNAS_CSV if c not in (lector.fieldnames or [])]
        if faltantes:
            raise ValueError(f"Faltan columnas en el CSV: {', '.join(faltantes)}")

        for fila in lector:
            codigo = (fila.get("ruta") or "").strip().upper()
            try:
                datos = validar_fila(fila)
                clave = (datos["codigo"], datos["tramo"])
                if clave in claves_vistas:
                    raise ValueError(f"tramo {datos['tramo']} repetido para la ruta en el archivo")
                turno_previo = turno_de_ruta.get(datos["codigo"])
                if turno_previo is not None and turno_previo != datos["turno"]:
                    raise ValueError(
                        f"turno {datos['turno']} distinto al de los otros tramos ({turno_previo})"
                    )
            except ValueError as error:
                tramo_texto = (fila.get("tramo") or "").strip()
                etiqueta = f"{codigo} tramo {tramo_texto}" if tramo_texto else codigo
                lectura.rechazadas.append(FilaRechazada(lector.line_num, etiqueta, str(error)))
                continue
            claves_vistas.add(clave)
            turno_de_ruta[datos["codigo"]] = datos["turno"]
            lectura.validas.append(datos)

    return lectura


def guardar(engine: Engine, filas: list[dict]) -> tuple[int, int]:
    """Inserta o actualiza por (codigo, tramo). Devuelve (creadas, actualizadas)."""
    if not filas:
        return 0, 0

    tabla = ZonaRuta.__table__
    sentencia = insert(ZonaRuta).values(filas)
    nuevos = sentencia.excluded
    sentencia = sentencia.on_conflict_do_update(
        constraint="uq_zonas_ruta_codigo_tramo",
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


def contar(engine: Engine) -> dict:
    """Totales de la tabla: tramos, rutas distintas, rutas por turno y tramos por revisar."""
    with engine.connect() as conexion:
        rutas_por_turno = Counter(
            dict(
                conexion.execute(
                    select(ZonaRuta.turno, func.count(func.distinct(ZonaRuta.codigo))).group_by(
                        ZonaRuta.turno
                    )
                ).all()
            )
        )
        total_tramos = conexion.scalar(select(func.count()).select_from(ZonaRuta))
        total_rutas = conexion.scalar(select(func.count(func.distinct(ZonaRuta.codigo))))
        revisar = conexion.scalar(
            select(func.count()).select_from(ZonaRuta).where(ZonaRuta.revisar)
        )
    return {
        "total_tramos": total_tramos,
        "total_rutas": total_rutas,
        "rutas_por_turno": {t.value: rutas_por_turno[t.value] for t in Turno},
        "tramos_por_revisar": revisar,
    }


def importar(engine: Engine, ruta: Path) -> ResultadoImportacion:
    lectura = leer_csv(ruta)  # falla antes de tocar la base si no hay archivo
    migrar_tramos(engine)  # crea la tabla o la lleva a (codigo, tramo)

    creadas, actualizadas = guardar(engine, lectura.validas)

    return ResultadoImportacion(
        leidas=lectura.leidas,
        creadas=creadas,
        actualizadas=actualizadas,
        sin_cambios=len(lectura.validas) - creadas - actualizadas,
        rechazadas=lectura.rechazadas,
        **contar(engine),
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
    except (ArchivoNoEncontrado, ValueError, TramosInvalidos) as error:
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

    print(f"\nEn la tabla zonas_ruta: {resultado.total_rutas} rutas, {resultado.total_tramos} tramos")
    print("Rutas por turno:")
    for turno, cantidad in resultado.rutas_por_turno.items():
        print(f"  {turno}: {cantidad}")
    print(f"Tramos por revisar (revisar=true): {resultado.tramos_por_revisar}")


if __name__ == "__main__":
    main()
