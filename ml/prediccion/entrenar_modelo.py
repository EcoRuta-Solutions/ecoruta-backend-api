from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ml.prediccion.features import (
        FEATURE_NAMES,
        EjemploEntrenamiento,
        construir_ejemplos_entrenamiento,
    )
else:
    from .features import (
        FEATURE_NAMES,
        EjemploEntrenamiento,
        construir_ejemplos_entrenamiento,
    )

from app.database import SessionLocal
from app.models.lectura import Lectura
from app.models.nodo import Nodo

MIN_EJEMPLOS_VALIDOS = 50
MIN_EJEMPLOS_ENTRENAMIENTO = 30
MIN_EJEMPLOS_VALIDACION = 10
FRACCION_VALIDACION = 0.2
TASA_MINIMA_BASELINE = 0.001
RUTA_MODELO = Path(__file__).resolve().parent / "modelos" / "modelo_lgbm.joblib"


def cargar_ejemplos() -> tuple[list[EjemploEntrenamiento], int, int, list[datetime]]:
    db = SessionLocal()
    try:
        registros = (
            db.query(
                Lectura.nodo_id,
                Nodo.umbral_critico,
                Lectura.fill_pct,
                Lectura.timestamp,
            )
            .join(Nodo, Nodo.id == Lectura.nodo_id)
            .order_by(Lectura.timestamp.asc(), Lectura.id.asc())
            .all()
        )
    finally:
        db.close()

    lecturas_por_nodo: dict[int, list[dict[str, Any]]] = defaultdict(list)
    umbrales: dict[int, float] = {}
    fechas = []
    for nodo_id, umbral, fill_pct, timestamp in registros:
        lecturas_por_nodo[nodo_id].append(
            {"timestamp": timestamp, "fill_pct": fill_pct}
        )
        umbrales[nodo_id] = float(umbral)
        fechas.append(timestamp)

    ejemplos: list[EjemploEntrenamiento] = []
    censurados = 0
    for nodo_id, lecturas in lecturas_por_nodo.items():
        nodo_ejemplos, nodo_censurados = construir_ejemplos_entrenamiento(
            lecturas, umbrales[nodo_id]
        )
        ejemplos.extend(nodo_ejemplos)
        censurados += nodo_censurados

    return ejemplos, censurados, len(registros), fechas


def separar_temporalmente(
    ejemplos: list[EjemploEntrenamiento], fechas_lecturas: list[datetime]
) -> tuple[list[EjemploEntrenamiento], list[EjemploEntrenamiento], int]:
    if not fechas_lecturas:
        return [], [], 0

    fechas_ordenadas = sorted(fechas_lecturas)
    indice_corte = min(
        len(fechas_ordenadas) - 1,
        max(1, int(len(fechas_ordenadas) * (1 - FRACCION_VALIDACION))),
    )
    fecha_corte = fechas_ordenadas[indice_corte]
    entrenamiento = [e for e in ejemplos if e.fecha_cruce < fecha_corte]
    validacion = [e for e in ejemplos if e.fecha_origen >= fecha_corte]
    excluidos_frontera = len(ejemplos) - len(entrenamiento) - len(validacion)
    return entrenamiento, validacion, excluidos_frontera


def mensaje_faltan_datos(
    validos: int, total: int, entrenamiento: int | None = None, validacion: int | None = None
) -> str:
    if entrenamiento is not None and validacion is not None:
        faltan_entrenamiento = max(0, MIN_EJEMPLOS_ENTRENAMIENTO - entrenamiento)
        faltan_validacion = max(0, MIN_EJEMPLOS_VALIDACION - validacion)
        return (
            f"Faltan datos para la división temporal: hay {validos} objetivos "
            f"observables de {total} lecturas; se requieren al menos "
            f"{MIN_EJEMPLOS_ENTRENAMIENTO} de entrenamiento y "
            f"{MIN_EJEMPLOS_VALIDACION} de validación (faltan "
            f"{faltan_entrenamiento} y {faltan_validacion}, respectivamente)."
        )
    faltan = max(0, MIN_EJEMPLOS_VALIDOS - validos)
    return (
        f"Faltan datos: hay {validos} objetivos observables de {total} lecturas; "
        f"se requieren al menos {MIN_EJEMPLOS_VALIDOS} (faltan {faltan})."
    )


def entrenar() -> int:
    from joblib import dump
    from lightgbm import LGBMRegressor
    from pandas import DataFrame
    from sklearn.metrics import mean_absolute_error

    ejemplos, censurados, total, fechas = cargar_ejemplos()
    porcentaje_censurado = (100 * censurados / total) if total else 0.0
    print(
        f"Ejemplos censurados excluidos: {censurados}/{total} "
        f"({porcentaje_censurado:.1f} % del total)."
    )

    if len(ejemplos) < MIN_EJEMPLOS_VALIDOS:
        print(mensaje_faltan_datos(len(ejemplos), total))
        return 1

    entrenamiento, validacion, frontera = separar_temporalmente(ejemplos, fechas)
    if (
        len(entrenamiento) < MIN_EJEMPLOS_ENTRENAMIENTO
        or len(validacion) < MIN_EJEMPLOS_VALIDACION
    ):
        print(
            mensaje_faltan_datos(
                len(ejemplos), total, len(entrenamiento), len(validacion)
            )
        )
        return 1

    print(f"Ejemplos descartados en la frontera temporal: {frontera}.")
    x_train = DataFrame(
        [[e.features[name] for name in FEATURE_NAMES] for e in entrenamiento],
        columns=FEATURE_NAMES,
    )
    y_train = [e.horas_hasta_critico for e in entrenamiento]
    x_valid = DataFrame(
        [[e.features[name] for name in FEATURE_NAMES] for e in validacion],
        columns=FEATURE_NAMES,
    )
    y_valid = [e.horas_hasta_critico for e in validacion]

    model = LGBMRegressor(
        n_estimators=200,
        learning_rate=0.05,
        num_leaves=15,
        random_state=42,
        verbosity=-1,
    )
    model.fit(x_train, y_train)
    predicciones_modelo = model.predict(x_valid)
    tasa_minima = TASA_MINIMA_BASELINE
    predicciones_lineales = [
        max(0.0, e.features["umbral_critico"] - e.features["fill_pct_actual"])
        / max(e.features["tasa_llenado_pct_hora"], tasa_minima)
        for e in validacion
    ]
    mae_modelo = float(mean_absolute_error(y_valid, predicciones_modelo))
    mae_lineal = float(mean_absolute_error(y_valid, predicciones_lineales))

    metadata = {
        "modelo": model,
        "features": list(FEATURE_NAMES),
        "fecha_entrenamiento": datetime.now(timezone.utc).isoformat(),
        "mae_validacion_horas": mae_modelo,
        "mae_lineal_horas": mae_lineal,
        "ejemplos_entrenamiento": len(entrenamiento),
        "ejemplos_validacion": len(validacion),
    }
    RUTA_MODELO.parent.mkdir(parents=True, exist_ok=True)
    dump(metadata, RUTA_MODELO)

    print(f"MAE LightGBM: {mae_modelo:.4f} horas.")
    print(f"MAE extrapolación lineal: {mae_lineal:.4f} horas.")
    print(f"Modelo guardado en: {RUTA_MODELO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(entrenar())