from datetime import datetime, timedelta, timezone

from ml.prediccion.features import (
    construir_ejemplos_entrenamiento,
    construir_features,
    es_vaciado,
)


def lecturas_con_horas(valores: list[float]) -> list[dict[str, object]]:
    inicio = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        {"timestamp": inicio + timedelta(hours=hora), "fill_pct": fill_pct}
        for hora, fill_pct in enumerate(valores)
    ]


def test_detecta_caida_de_vaciado_por_umbral() -> None:
    assert es_vaciado(80, 60)
    assert not es_vaciado(80, 61)
    assert not es_vaciado(20, 40)


def test_reinicia_tasa_y_minutos_desde_vaciado() -> None:
    features = construir_features(lecturas_con_horas([60, 10, 20]), 80)

    assert features[1]["tasa_llenado_pct_hora"] == 0
    assert features[1]["minutos_desde_ultimo_vaciado"] == 0
    assert features[2]["tasa_llenado_pct_hora"] == 10
    assert features[2]["minutos_desde_ultimo_vaciado"] == 60


def test_etiqueta_cruce_interpolado_y_excluye_censurados() -> None:
    ejemplos, censurados = construir_ejemplos_entrenamiento(
        lecturas_con_horas([10, 30, 60, 2, 20, 45, 85]), 80
    )

    assert len(ejemplos) == 4
    assert censurados == 3
    assert [ejemplo.horas_hasta_critico for ejemplo in ejemplos] == [
        2.875,
        1.875,
        0.875,
        0.0,
    ]
    assert ejemplos[0].features["fill_pct_actual"] == 2


def test_historial_sin_cruce_solo_produce_ejemplos_censurados() -> None:
    ejemplos, censurados = construir_ejemplos_entrenamiento(
        lecturas_con_horas([10, 20, 30]), 80
    )

    assert ejemplos == []
    assert censurados == 3