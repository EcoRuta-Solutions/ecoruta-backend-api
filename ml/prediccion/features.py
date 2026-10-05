from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

FEATURE_NAMES = (
    "fill_pct_actual",
    "tasa_llenado_pct_hora",
    "hora_del_dia",
    "dia_semana",
    "umbral_critico",
    "minutos_desde_ultimo_vaciado",
)
VACIO_DROP_PCT = 20.0
RATE_WINDOW_READINGS = 5
MIN_LECTURAS_MODELO = 5


@dataclass(frozen=True)
class EjemploEntrenamiento:
    features: dict[str, float]
    horas_hasta_critico: float
    fecha_origen: datetime
    fecha_cruce: datetime


def _value(reading: Any, name: str) -> Any:
    if isinstance(reading, Mapping):
        return reading[name]
    return getattr(reading, name)


def _timestamp(value: Any) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise TypeError("Cada lectura debe tener un timestamp datetime válido")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _ordered_points(readings: Sequence[Any]) -> list[tuple[datetime, float]]:
    points = [
        (_timestamp(_value(reading, "timestamp")), float(_value(reading, "fill_pct")))
        for reading in readings
    ]
    return sorted(points, key=lambda point: point[0])


def es_vaciado(fill_anterior: float, fill_actual: float) -> bool:
    return fill_anterior - fill_actual >= VACIO_DROP_PCT


def construir_features(
    readings: Sequence[Any], umbral_critico: float
) -> list[dict[str, float]]:
    """Construye las features cronológicas y reinicia la tasa tras un vaciado."""
    points = _ordered_points(readings)
    if not points:
        return []

    rows: list[dict[str, float]] = []
    cycle_start = 0
    last_reset_at = points[0][0]

    for index, (timestamp, fill_pct) in enumerate(points):
        if index and es_vaciado(points[index - 1][1], fill_pct):
            cycle_start = index
            last_reset_at = timestamp

        window_start = max(cycle_start, index - RATE_WINDOW_READINGS + 1)
        first_at, first_fill = points[window_start]
        elapsed_hours = (timestamp - first_at).total_seconds() / 3600
        rate = (
            max(0.0, (fill_pct - first_fill) / elapsed_hours)
            if elapsed_hours > 0
            else 0.0
        )

        rows.append(
            {
                "fill_pct_actual": fill_pct,
                "tasa_llenado_pct_hora": rate,
                "hora_del_dia": float(timestamp.hour),
                "dia_semana": float(timestamp.weekday()),
                "umbral_critico": float(umbral_critico),
                "minutos_desde_ultimo_vaciado": max(
                    0.0, (timestamp - last_reset_at).total_seconds() / 60
                ),
            }
        )
    return rows


def construir_ejemplos_entrenamiento(
    readings: Sequence[Any], umbral_critico: float
) -> tuple[list[EjemploEntrenamiento], int]:
    """Devuelve objetivos observados y el número de lecturas censuradas."""
    points = _ordered_points(readings)
    rows = construir_features(readings, umbral_critico)
    ejemplos: list[EjemploEntrenamiento] = []
    censurados = 0

    for index, (timestamp, fill_pct) in enumerate(points):
        fecha_cruce: datetime | None = None
        if fill_pct >= umbral_critico:
            fecha_cruce = timestamp
        else:
            for future_index in range(index + 1, len(points)):
                previous_at, previous_fill = points[future_index - 1]
                future_at, future_fill = points[future_index]

                if es_vaciado(previous_fill, future_fill):
                    break
                if future_fill >= umbral_critico and future_fill > previous_fill:
                    fraction = (umbral_critico - previous_fill) / (
                        future_fill - previous_fill
                    )
                    fecha_cruce = previous_at + (future_at - previous_at) * fraction
                    break

        if fecha_cruce is None:
            censurados += 1
        else:
            horas_hasta_critico = max(
                0.0, (fecha_cruce - timestamp).total_seconds() / 3600
            )
            ejemplos.append(
                EjemploEntrenamiento(
                    features=rows[index],
                    horas_hasta_critico=horas_hasta_critico,
                    fecha_origen=timestamp,
                    fecha_cruce=fecha_cruce,
                )
            )

    return ejemplos, censurados