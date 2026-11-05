r"""Importa los puntos críticos oficiales de residuos del distrito de Trujillo.

Lee `data/puntos_criticos_trujillo.csv` (listado oficial, Tramo III), valida
cada fila y guarda las válidas en la tabla `puntos_criticos`. Las filas
inválidas se reportan y se saltan; no detienen la importación.

Es idempotente: actualiza por `codigo_unico`, así que correrlo dos veces no
duplica nada. Crea la tabla (con su índice GiST) si todavía no existe.

Uso:
    .\venv\Scripts\python.exe scripts\importar_puntos_criticos.py
    .\venv\Scripts\python.exe scripts\importar_puntos_criticos.py --archivo otro.csv
"""

import argparse
import csv
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from sqlalchemy import func, literal_column, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from app.models.punto_critico import EstadoPuntoCritico, PuntoCritico

ARCHIVO_POR_DEFECTO = RAIZ / "data" / "puntos_criticos_trujillo.csv"

COLUMNAS_CSV = (
    "codigo",
    "estado",
    "priorizacion_obligatoria",
    "lat",
    "lon",
    "este_utm17s",
    "norte_utm17s",
    "direccion",
    "referencia",
)

# Rango del distrito de Trujillo en WGS84 (EPSG:4326).
LAT_MIN, LAT_MAX = -8.13, -8.08
LON_MIN, LON_MAX = -79.06, -78.99

PATRON_CODIGO = re.compile(r"^\d{6}-\d+$")
PRIORIZACION = {"SI": True, "SÍ": True, "NO": False}

# Campos que se sobrescriben cuando el código ya existe.
CAMPOS_ACTUALIZABLES = (
    "estado",
    "priorizacion_obligatoria",
    "direccion",
    "referencia",
    "este_utm17s",
    "norte_utm17s",
    "ubicacion",
)


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
    por_estado: dict[str, int]
    por_prioridad: dict[str, int]


def _coordenada(valor: str | None, nombre: str) -> float:
    try:
        return float((valor or "").strip())
    except ValueError:
        raise ValueError(f"{nombre} no es numérico: {valor!r}")


def _entero_opcional(valor: str | None, nombre: str) -> int | None:
    valor = (valor or "").strip()
    if not valor:
        return None
    try:
        return int(valor)
    except ValueError:
        raise ValueError(f"{nombre} no es entero: {valor!r}")


def validar_fila(fila: dict) -> dict:
    """Devuelve los datos listos para guardar o lanza ValueError con el motivo."""
    codigo = (fila.get("codigo") or "").strip()
    if not codigo:
        raise ValueError("codigo vacío")
    if not PATRON_CODIGO.match(codigo):
        raise ValueError(f"codigo con formato inválido: {codigo!r}")

    estado_texto = (fila.get("estado") or "").strip().lower()
    try:
        estado = EstadoPuntoCritico(estado_texto)
    except ValueError:
        raise ValueError(f"estado inválido: {fila.get('estado')!r}")

    prioridad_texto = (fila.get("priorizacion_obligatoria") or "").strip().upper()
    if prioridad_texto not in PRIORIZACION:
        raise ValueError(
            "priorizacion_obligatoria inválida: "
            f"{fila.get('priorizacion_obligatoria')!r}"
        )

    lat = _coordenada(fila.get("lat"), "lat")
    lon = _coordenada(fila.get("lon"), "lon")
    if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
        raise ValueError(
            f"coordenadas fuera del rango de Trujillo: lat={lat}, lon={lon}"
        )

    direccion = (fila.get("direccion") or "").strip()
    if not direccion:
        raise ValueError("direccion vacía")

    return {
        "codigo_unico": codigo,
        "estado": estado,
        "priorizacion_obligatoria": PRIORIZACION[prioridad_texto],
        "direccion": direccion,
        "referencia": (fila.get("referencia") or "").strip() or None,
        "este_utm17s": _entero_opcional(fila.get("este_utm17s"), "este_utm17s"),
        "norte_utm17s": _entero_opcional(fila.get("norte_utm17s"), "norte_utm17s"),
        "lat": lat,
        "lon": lon,
    }


def leer_csv(ruta: Path) -> LecturaCsv:
    lectura = LecturaCsv()
    codigos_vistos: set[str] = set()

    # utf-8-sig descarta el BOM del archivo oficial.
    with open(ruta, encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo)
        faltantes = [c for c in COLUMNAS_CSV if c not in (lector.fieldnames or [])]
        if faltantes:
            raise ValueError(f"Faltan columnas en el CSV: {', '.join(faltantes)}")

        for fila in lector:
            codigo = (fila.get("codigo") or "").strip()
            try:
                datos = validar_fila(fila)
                if codigo in codigos_vistos:
                    raise ValueError("codigo repetido en el archivo")
            except ValueError as error:
                lectura.rechazadas.append(
                    FilaRechazada(lector.line_num, codigo, str(error))
                )
                continue
            codigos_vistos.add(codigo)
            lectura.validas.append(datos)

    return lectura


def guardar(engine: Engine, filas: list[dict]) -> tuple[int, int]:
    """Inserta o actualiza por codigo_unico. Devuelve (creadas, actualizadas)."""
    if not filas:
        return 0, 0

    valores = []
    for fila in filas:
        datos = {k: v for k, v in fila.items() if k not in ("lat", "lon")}
        datos["ubicacion"] = func.ST_SetSRID(
            func.ST_MakePoint(fila["lon"], fila["lat"]), 4326
        )
        valores.append(datos)

    sentencia = insert(PuntoCritico).values(valores)
    tabla = PuntoCritico.__table__
    nuevos = sentencia.excluded
    sentencia = sentencia.on_conflict_do_update(
        index_elements=[tabla.c.codigo_unico],
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


def contar(engine: Engine) -> tuple[dict[str, int], dict[str, int]]:
    with engine.connect() as conexion:
        por_estado = Counter(
            dict(
                conexion.execute(
                    select(PuntoCritico.estado, func.count()).group_by(
                        PuntoCritico.estado
                    )
                ).all()
            )
        )
        por_prioridad = Counter(
            dict(
                conexion.execute(
                    select(
                        PuntoCritico.priorizacion_obligatoria, func.count()
                    ).group_by(PuntoCritico.priorizacion_obligatoria)
                ).all()
            )
        )

    return (
        {e.value: por_estado[e] for e in EstadoPuntoCritico},
        {
            "prioritarios": por_prioridad[True],
            "no_prioritarios": por_prioridad[False],
        },
    )


def importar(engine: Engine, ruta: Path) -> ResultadoImportacion:
    PuntoCritico.__table__.create(engine, checkfirst=True)

    lectura = leer_csv(ruta)
    creadas, actualizadas = guardar(engine, lectura.validas)
    por_estado, por_prioridad = contar(engine)

    return ResultadoImportacion(
        leidas=lectura.leidas,
        creadas=creadas,
        actualizadas=actualizadas,
        sin_cambios=len(lectura.validas) - creadas - actualizadas,
        rechazadas=lectura.rechazadas,
        por_estado=por_estado,
        por_prioridad=por_prioridad,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--archivo",
        type=Path,
        default=ARCHIVO_POR_DEFECTO,
        help="CSV a importar (por defecto, el listado oficial en data/)",
    )
    args = parser.parse_args()

    from app.database import engine

    resultado = importar(engine, args.archivo)

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

    total = sum(resultado.por_estado.values())
    print(f"\nEn la tabla puntos_criticos: {total}")
    print("Por estado:")
    for estado, cantidad in resultado.por_estado.items():
        print(f"  {estado}: {cantidad}")
    print("Por priorización obligatoria:")
    for prioridad, cantidad in resultado.por_prioridad.items():
        print(f"  {prioridad}: {cantidad}")


if __name__ == "__main__":
    main()
