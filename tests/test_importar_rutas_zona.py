"""Importador de zonas de ruta.

El CSV oficial (data/rutas_zona_trujillo.csv) todavía no está en el repo: estas
pruebas usan filas de PRUEBA, inventadas solo para ejercitar el importador. No
son datos de SEGAT.
"""

import csv
from datetime import time

import pytest
from sqlalchemy import func, select

from app.models.zona_ruta import ZonaRuta
from conftest import importador_zonas as importador

CABECERA = list(importador.COLUMNAS_CSV)

# ruta, turno, tramo, sectores, recojo_inicio, recojo_fin, sacar_inicio, sacar_fin
FILAS_PRUEBA = [
    ["M-1", "mañana", "Tramo prueba A", "Sector prueba 1", "05:00", "13:00", "04:00", "05:00"],
    ["M-10", "Mañana", "", "", "06:00", "12:00", "", ""],
    ["T-1", "tarde", "Tramo prueba B", "Sector prueba 2", "13:00", "21:00", "12:00", "13:00"],
    ["N-1", "noche", "Tramo prueba C", "Sector prueba 3", "21:00", "03:00", "20:00", "21:00"],
    ["N-9", "noche", "Tramo prueba D", "Sector prueba 4", "23:00", "24:00", "22:00", "23:00"],
]


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


def fila(**cambios):
    base = dict(zip(CABECERA, FILAS_PRUEBA[0]))
    base.update(cambios)
    return base


def zonas(engine):
    with engine.connect() as conexion:
        return {z.codigo: z for z in conexion.execute(select(ZonaRuta)).all()}


# --- Validación ---------------------------------------------------------------


def test_validar_fila_normaliza_turno_y_horas():
    datos = importador.validar_fila(fila(ruta=" m-1 ", turno="Mañana"))

    assert datos["codigo"] == "M-1"
    assert datos["turno"] == "manana"
    assert (datos["recojo_inicio"], datos["recojo_fin"]) == (time(5), time(13))
    assert datos["cruza_medianoche"] is False
    assert datos["revisar"] is False


@pytest.mark.parametrize(
    ("inicio", "fin", "cruza"),
    [
        ("21:00", "05:00", True),
        ("22:30", "02:15", True),
        ("05:00", "13:00", False),
        ("23:00", "24:00", False),  # termina justo a medianoche
        ("21:00", "00:00", False),
    ],
)
def test_cruce_de_medianoche(inicio, fin, cruza):
    datos = importador.validar_fila(
        fila(turno="noche", recojo_inicio=inicio, recojo_fin=fin)
    )

    assert datos["cruza_medianoche"] is cruza


def test_24_00_se_guarda_como_medianoche():
    datos = importador.validar_fila(fila(recojo_inicio="23:00", recojo_fin="24:00"))

    assert datos["recojo_fin"] == time(0, 0)


def test_n9_queda_en_revisar_por_codigo():
    assert importador.validar_fila(fila(ruta="N-9", turno="noche"))["revisar"] is True


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [("true", True), ("SI", True), ("1", True), ("false", False), ("no", False), ("", False)],
)
def test_columna_revisar_opcional(valor, esperado):
    assert importador.validar_fila(fila(revisar=valor))["revisar"] is esperado


@pytest.mark.parametrize(
    ("cambios", "motivo"),
    [
        ({"ruta": " "}, "ruta vacía"),
        ({"turno": "madrugada"}, "turno inválido"),
        ({"recojo_inicio": ""}, "recojo_inicio vacío"),
        ({"recojo_fin": "5pm"}, "formato HH:MM"),
        ({"recojo_fin": "25:00"}, "fuera de rango"),
        ({"sacar_basura_fin": ""}, "deben venir juntos"),
        ({"revisar": "quizas"}, "revisar inválido"),
    ],
)
def test_validar_fila_rechaza_datos_invalidos(cambios, motivo):
    with pytest.raises(ValueError, match=motivo):
        importador.validar_fila(fila(**cambios))


def test_archivo_inexistente_da_error_claro(tmp_path):
    with pytest.raises(importador.ArchivoNoEncontrado, match="rutas_zona_trujillo.csv"):
        importador.leer_csv(tmp_path / "no_existe.csv")


def test_faltan_columnas(escribir):
    ruta = escribir([["M-1", "manana"]], cabecera=["ruta", "turno"])

    with pytest.raises(ValueError, match="Faltan columnas"):
        importador.leer_csv(ruta)


def test_leer_csv_reporta_invalidas_y_repetidas(escribir):
    mala = ["T-2", "madrugada", "", "", "13:00", "21:00", "", ""]
    ruta = escribir([FILAS_PRUEBA[0], mala, FILAS_PRUEBA[0]])

    lectura = importador.leer_csv(ruta)

    assert [f["codigo"] for f in lectura.validas] == ["M-1"]
    assert [(r.linea, r.codigo) for r in lectura.rechazadas] == [(3, "T-2"), (4, "M-1")]
    assert "repetida" in lectura.rechazadas[1].motivo


# --- Importación ---------------------------------------------------------------


def test_importacion_es_idempotente(db_limpia, escribir):
    ruta = escribir(FILAS_PRUEBA)

    primera = importador.importar(db_limpia, ruta)
    segunda = importador.importar(db_limpia, ruta)

    assert (primera.creadas, primera.actualizadas, primera.sin_cambios) == (5, 0, 0)
    assert (segunda.creadas, segunda.actualizadas, segunda.sin_cambios) == (0, 0, 5)
    assert segunda.total == 5
    assert segunda.por_turno == {"manana": 2, "tarde": 1, "noche": 2}
    assert segunda.revisar == 1


def test_importacion_guarda_cruce_y_n9_en_revisar(db_limpia, escribir):
    importador.importar(db_limpia, escribir(FILAS_PRUEBA))

    guardadas = zonas(db_limpia)
    assert guardadas["N-1"].cruza_medianoche is True
    assert guardadas["T-1"].cruza_medianoche is False
    n9 = guardadas["N-9"]
    assert n9.revisar is True
    # Se importa tal cual: 23:00–24:00 (00:00), sin "arreglar" el hueco.
    assert (n9.recojo_inicio, n9.recojo_fin) == (time(23), time(0))
    assert guardadas["M-10"].tramo is None and guardadas["M-10"].sacar_basura_inicio is None
    assert {z.turno for z in guardadas.values()} == {"manana", "tarde", "noche"}


def test_importacion_actualiza_por_codigo_y_revisar_desde_csv(db_limpia, escribir):
    importador.importar(db_limpia, escribir(FILAS_PRUEBA))
    cabecera = [*CABECERA, "revisar"]
    cambiadas = [[*f, ""] for f in FILAS_PRUEBA]
    cambiadas[0][4] = "05:30"  # M-1 cambia su inicio
    cambiadas[2][-1] = "true"  # T-1 marcada como dudosa en el archivo
    cambiadas[4][-1] = "false"  # N-9 sigue en revisar por código

    resultado = importador.importar(db_limpia, escribir(cambiadas, cabecera, "v2.csv"))

    assert (resultado.creadas, resultado.actualizadas, resultado.sin_cambios) == (0, 2, 3)
    guardadas = zonas(db_limpia)
    assert guardadas["M-1"].recojo_inicio == time(5, 30)
    assert guardadas["T-1"].revisar is True
    assert guardadas["N-9"].revisar is True
    with db_limpia.connect() as conexion:
        assert conexion.scalar(select(func.count()).select_from(ZonaRuta)) == 5


def test_importacion_sin_archivo_no_toca_la_base(db_limpia, tmp_path):
    with pytest.raises(importador.ArchivoNoEncontrado):
        importador.importar(db_limpia, tmp_path / "no_existe.csv")

    assert zonas(db_limpia) == {}
