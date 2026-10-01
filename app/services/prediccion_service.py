from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib

from ml.prediccion.features import FEATURE_NAMES, MIN_LECTURAS_MODELO, construir_features

RUTA_MODELO = (
    Path(__file__).resolve().parents[2]
    / "ml"
    / "prediccion"
    / "modelos"
    / "modelo_lgbm.joblib"
)


@lru_cache(maxsize=1)
def cargar_modelo() -> dict[str, Any] | None:
    try:
        bundle = joblib.load(RUTA_MODELO)
    except Exception:
        return None
    if not isinstance(bundle, dict) or bundle.get("features") != list(FEATURE_NAMES):
        return None
    return bundle


def estimar_horas_critico(
    nodo: Any,
    lecturas: list[Any],
    modelo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    calculado_en = datetime.now(timezone.utc)
    umbral = float(nodo.umbral_critico)

    if not lecturas:
        return {
            "fill_pct_actual": None,
            "horas_estimadas": None,
            "fecha_estimada_critico": None,
            "metodo": "lineal",
            "confianza": 0.0,
            "calculado_en": calculado_en,
        }

    features = construir_features(lecturas, umbral)[-1]
    fill_actual = features["fill_pct_actual"]
    if fill_actual >= umbral:
        horas = 0.0
        metodo = "lineal"
        confianza = 1.0
    elif features["tasa_llenado_pct_hora"] <= 0:
        horas = None
        metodo = "lineal"
        confianza = 0.0
    else:
        if modelo is None:
            modelo = cargar_modelo()

        horas = None
        metodo = "lineal"
        confianza = min(0.7, 0.2 + 0.1 * min(len(lecturas), 5))
        if len(lecturas) >= MIN_LECTURAS_MODELO and modelo is not None:
            try:
                from pandas import DataFrame

                vector = DataFrame(
                    [[features[name] for name in FEATURE_NAMES]],
                    columns=FEATURE_NAMES,
                )
                prediccion = float(modelo["modelo"].predict(vector)[0])
                if not math.isfinite(prediccion):
                    raise ValueError("El modelo produjo una predicción no finita")
                horas = max(0.0, prediccion)
                metodo = "modelo"
                mae = max(0.0, float(modelo.get("mae_validacion_horas", 0.0)))
                confianza = max(0.0, min(1.0, 1 - mae / max(horas, mae, 0.1)))
            except (IndexError, KeyError, TypeError, ValueError, AttributeError):
                horas = None

        if horas is None:
            tasa = features["tasa_llenado_pct_hora"]
            horas = (umbral - fill_actual) / tasa

    fecha_estimada = (
        calculado_en + timedelta(hours=horas) if horas is not None else None
    )
    return {
        "fill_pct_actual": fill_actual,
        "horas_estimadas": horas,
        "fecha_estimada_critico": fecha_estimada,
        "metodo": metodo,
        "confianza": confianza,
        "calculado_en": calculado_en,
    }