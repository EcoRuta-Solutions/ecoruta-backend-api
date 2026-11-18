"""Importador de zonas de ruta: una fila por tramo, única por (ruta, tramo).

Usa tests/fixtures/rutas_zona_trujillo.csv, copia idéntica del CSV real
(66 tramos de 19 rutas). Los casos de error parten de filas reales con un
cambio puntual; no se inventan rutas.
"""

import csv
from datetime import time
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models.zona_ruta import ZonaRuta
from conftest import importador_zonas as importador

CSV_REAL = Path(__file__).parent / "fixtures" / "rutas_zona_trujillo.csv"

with open(CSV_REAL, encoding="utf-8-sig", newline="") as _archivo:
    _lector = csv.reader(_archivo)
    CABECERA = next(_lector)
    FILAS_PRUEBA = [fila for fila in _lector]  # las 66 filas reales


def fila_real(ruta_base="M-1", tramo_base="1", **cambios):
    """Una fila real del CSV, con cambios puntuales para probar validaciones."""
    base = next(
        dict(zip(CABECERA, f)) for f in FILAS_PRUEBA if f[0] == ruta_base and f[2] == tramo_base
    )
    base.update(cambios)
    return base


@pytest.fixture
def escribir(tmp_path):
    def escribir(filas, cabecera=CABECERA, nombre="zonas.csv"):
        ruta = tmp_path / nombre
        with open(ruta, "w", encoding="utf-8-sig", newline="") as archivo:
            escritor = csv.writer(archivo)
            escritor.writerow(cabecera)
            escritor.writerows(filas)
        return ruta

    return escribir


def tramos(engine):
    with engine.connect() as conexion:
        return {(z.codigo, z.tramo): z for z in conexion.execute(select(ZonaRuta)).all()}


# --- CSV real ------------------------------------------------------------------------------


def test_csv_real_tiene_la_forma_esperada():
    lectura = importador.leer_csv(CSV_REAL)

    assert lectura.leidas == 66
    assert lectura.rechazadas == []
    assert len({f["codigo"] for f in lectura.validas}) == 19


def test_importa_el_csv_real_completo(db_limpia):
    resultado = importador.importar(db_limpia, CSV_REAL)

    assert (resultado.leidas, resultado.creadas, resultado.actualizadas) == (66, 66, 0)
    assert resultado.rechazadas == []
    assert (resultado.total_rutas, resultado.total_tramos) == (19, 66)
    assert resultado.rutas_por_turno == {"manana": 10, "tarde": 0, "noche": 9}
    assert resultado.tramos_por_revisar == 4  # los 4 tramos de N-9, marcados por código

    guardados = tramos(db_limpia)
    assert [t for (c, t) in sorted(guardados) if c == "M-1"] == [1, 2, 3, 4, 5]
    assert guardados[("M-1", 5)].recojo_inicio == time(12, 0)
    assert len([k for k in guardados if k[0] == "N-3"]) == 6
    assert guardados[("N-1", 1)].cruza_medianoche is True  # 21:30–04:00
    assert guardados[("M-1", 1)].cruza_medianoche is False
    assert {guardados[("N-9", t)].revisar for t in (1, 2, 3, 4)} == {True}
    assert guardados[("N-8", 1)].revisar is False


def test_importacion_es_idempotente(db_limpia):
    importador.importar(db_limpia, CSV_REAL)

    segunda = importador.importar(db_limpia, CSV_REAL)

    assert (segunda.creadas, segunda.actualizadas, segunda.sin_cambios) == (0, 0, 66)
    assert (segunda.total_rutas, segunda.total_tramos) == (19, 66)
    with db_limpia.connect() as conexion:
        assert conexion.scalar(select(func.count()).select_from(ZonaRuta)) == 66


def test_actualiza_por_ruta_y_tramo(db_limpia, escribir):
    importador.importar(db_limpia, CSV_REAL)
    cambiadas = [list(f) for f in FILAS_PRUEBA]
    indice = next(i for i, f in enumerate(cambiadas) if f[0] == "M-1" and f[2] == "2")
    cambiadas[indice][4] = "07:45"  # recojo_inicio del tramo 2 de M-1

    resultado = importador.importar(db_limpia, escribir(cambiadas))

    assert (resultado.creadas, resultado.actualizadas, resultado.sin_cambios) == (0, 1, 65)
    guardados = tramos(db_limpia)
    assert guardados[("M-1", 2)].recojo_inicio == time(7, 45)
    assert guardados[("M-1", 1)].recojo_inicio == time(5, 30)  # el otro tramo no cambia


# --- Tramos repetidos y validación -----------------------------------------------------


def test_mismo_tramo_repetido_en_el_archivo_se_rechaza(escribir):
    repetida = list(FILAS_PRUEBA[1])  # M-1 tramo 2 otra vez
    lectura = importador.leer_csv(escribir([*FILAS_PRUEBA, repetida]))

    assert len(lectura.validas) == 66
    assert [(r.linea, r.codigo) for r in lectura.rechazadas] == [(68, "M-1 tramo 2")]
    assert "repetido" in lectura.rechazadas[0].motivo


def test_mismo_codigo_con_otro_tramo_si_se_acepta(escribir):
    lectura = importador.leer_csv(escribir(FILAS_PRUEBA[:5]))  # M-1 tramos 1..5

    assert [(f["codigo"], f["tramo"]) for f in lectura.validas] == [("M-1", t) for t in range(1, 6)]


def test_tramo_con_turno_distinto_al_de_su_ruta_se_rechaza(escribir):
    otra = list(FILAS_PRUEBA[1])
    otra[1] = "noche"
    lectura = importador.leer_csv(escribir([FILAS_PRUEBA[0], otra]))

    assert [r.codigo for r in lectura.rechazadas] == ["M-1 tramo 2"]
    assert "distinto" in lectura.rechazadas[0].motivo


@pytest.mark.parametrize(
    ("cambios", "motivo"),
    [
        ({"tramo": ""}, "tramo vacío"),
        ({"tramo": "0"}, "entero >= 1"),
        ({"tramo": "uno"}, "entero >= 1"),
        ({"turno": "madrugada"}, "turno inválido"),
        ({"recojo_fin": "25:00"}, "fuera de rango"),
        ({"revisar": "quizas"}, "revisar inválido"),
    ],
)
def test_validar_fila_rechaza(cambios, motivo):
    with pytest.raises(ValueError, match=motivo):
        importador.validar_fila(fila_real(**cambios))


def test_archivo_inexistente_da_error_claro(tmp_path):
    with pytest.raises(importador.ArchivoNoEncontrado, match="rutas_zona_trujillo.csv"):
        importador.leer_csv(tmp_path / "no_existe.csv")


# --- revisar por fila y por código --------------------------------------------------------


def test_revisar_por_fila_desde_el_csv(db_limpia, escribir):
    cabecera = [*CABECERA, "revisar"]
    filas = [[*f, ""] for f in FILAS_PRUEBA]
    indice = next(i for i, f in enumerate(filas) if f[0] == "M-3" and f[2] == "2")
    filas[indice][-1] = "true"

    resultado = importador.importar(db_limpia, escribir(filas, cabecera))

    guardados = tramos(db_limpia)
    assert guardados[("M-3", 2)].revisar is True
    assert guardados[("M-3", 1)].revisar is False  # solo esa fila
    assert resultado.tramos_por_revisar == 5  # 4 de N-9 + el de M-3


def test_n9_sigue_en_revisar_aunque_el_csv_diga_false(db_limpia, escribir):
    cabecera = [*CABECERA, "revisar"]
    filas = [[*f, "false"] for f in FILAS_PRUEBA]

    resultado = importador.importar(db_limpia, escribir(filas, cabecera))

    assert resultado.tramos_por_revisar == 4
    assert all(z.revisar for (c, _), z in tramos(db_limpia).items() if c == "N-9")
