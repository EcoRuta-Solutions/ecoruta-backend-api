import pytest
from sqlalchemy import func, select

from app.models.punto_critico import EstadoPuntoCritico, PuntoCritico
from conftest import FILAS_CSV_PRUEBA, importador


def fila(**cambios):
    base = dict(zip(
        importador.COLUMNAS_CSV,
        ["130101-9", "Potencial", "SI", "-8.1", "-79.03", "716000", "9104000",
         "Calle de prueba", ""],
    ))
    base.update(cambios)
    return base


def contar_filas(engine):
    with engine.connect() as conexion:
        return conexion.scalar(select(func.count()).select_from(PuntoCritico))


def test_validar_fila_normaliza_los_valores():
    datos = importador.validar_fila(fila(estado=" Recuperado ", priorizacion_obligatoria="no"))

    assert datos["codigo_unico"] == "130101-9"
    assert datos["estado"] is EstadoPuntoCritico.recuperado
    assert datos["priorizacion_obligatoria"] is False
    assert datos["referencia"] is None
    assert (datos["lat"], datos["lon"]) == (-8.1, -79.03)
    assert (datos["este_utm17s"], datos["norte_utm17s"]) == (716000, 9104000)


@pytest.mark.parametrize(
    ("cambios", "motivo"),
    [
        ({"lat": "-12.05"}, "fuera del rango"),  # Lima
        ({"lon": "-78.50"}, "fuera del rango"),
        ({"lat": "8.1"}, "fuera del rango"),  # signo invertido
        ({"lat": "abc"}, "no es numérico"),
        ({"codigo": "  "}, "codigo vacío"),
        ({"codigo": "PC-1"}, "formato inválido"),
        ({"estado": "Eliminado"}, "estado inválido"),
        ({"priorizacion_obligatoria": "TAL VEZ"}, "priorizacion_obligatoria"),
        ({"direccion": ""}, "direccion vacía"),
    ],
)
def test_validar_fila_rechaza_datos_invalidos(cambios, motivo):
    with pytest.raises(ValueError, match=motivo):
        importador.validar_fila(fila(**cambios))


def test_leer_csv_reporta_filas_invalidas_sin_abortar(escribir_csv):
    fuera_de_rango = ["130101-90", "Potencial", "SI", "-12.05", "-77.04", "", "",
                      "Plaza San Martín, Lima", ""]
    repetida = FILAS_CSV_PRUEBA[0]
    ruta = escribir_csv([*FILAS_CSV_PRUEBA[:2], fuera_de_rango, repetida, FILAS_CSV_PRUEBA[2]])

    lectura = importador.leer_csv(ruta)

    assert lectura.leidas == 5
    assert [f["codigo_unico"] for f in lectura.validas] == ["130101-1", "130101-2", "130101-3"]
    assert [(r.linea, r.codigo) for r in lectura.rechazadas] == [
        (4, "130101-90"),
        (5, "130101-1"),
    ]
    assert "fuera del rango" in lectura.rechazadas[0].motivo
    assert "repetido" in lectura.rechazadas[1].motivo


def test_csv_oficial_es_valido_y_cuadra_con_el_listado():
    lectura = importador.leer_csv(importador.ARCHIVO_POR_DEFECTO)

    assert lectura.leidas == 151
    assert lectura.rechazadas == []
    estados = [f["estado"] for f in lectura.validas]
    assert estados.count(EstadoPuntoCritico.potencial) == 110
    assert estados.count(EstadoPuntoCritico.recuperado) == 41
    assert sum(f["priorizacion_obligatoria"] for f in lectura.validas) == 109


def test_importacion_es_idempotente(db_limpia, csv_prueba):
    primera = importador.importar(db_limpia, csv_prueba)
    segunda = importador.importar(db_limpia, csv_prueba)

    assert (primera.creadas, primera.actualizadas, primera.sin_cambios) == (4, 0, 0)
    assert (segunda.creadas, segunda.actualizadas, segunda.sin_cambios) == (0, 0, 4)
    assert contar_filas(db_limpia) == 4
    assert segunda.por_estado == primera.por_estado == {"potencial": 2, "recuperado": 2}


def test_importacion_actualiza_por_codigo(db_limpia, escribir_csv):
    importador.importar(db_limpia, escribir_csv(FILAS_CSV_PRUEBA))
    cambiadas = [list(f) for f in FILAS_CSV_PRUEBA]
    cambiadas[0][1] = "Recuperado"
    cambiadas[0][4] = "-79.045000"

    resultado = importador.importar(db_limpia, escribir_csv(cambiadas, "cambiado.csv"))

    assert (resultado.creadas, resultado.actualizadas, resultado.sin_cambios) == (0, 1, 3)
    assert contar_filas(db_limpia) == 4
    with db_limpia.connect() as conexion:
        estado, lon = conexion.execute(
            select(PuntoCritico.estado, func.ST_X(PuntoCritico.ubicacion)).where(
                PuntoCritico.codigo_unico == "130101-1"
            )
        ).one()
    assert estado is EstadoPuntoCritico.recuperado
    assert lon == pytest.approx(-79.045)


def test_importacion_no_guarda_filas_rechazadas(db_limpia, escribir_csv):
    fuera_de_rango = ["130101-90", "Potencial", "SI", "-12.05", "-77.04", "", "",
                      "Plaza San Martín, Lima", ""]

    resultado = importador.importar(
        db_limpia, escribir_csv([FILAS_CSV_PRUEBA[0], fuera_de_rango])
    )

    assert resultado.leidas == 2
    assert resultado.creadas == 1
    assert [r.codigo for r in resultado.rechazadas] == ["130101-90"]
    assert contar_filas(db_limpia) == 1


def test_importacion_del_csv_oficial_dos_veces(db_limpia):
    importador.importar(db_limpia, importador.ARCHIVO_POR_DEFECTO)
    resultado = importador.importar(db_limpia, importador.ARCHIVO_POR_DEFECTO)

    assert resultado.leidas == 151
    assert (resultado.creadas, resultado.actualizadas, resultado.sin_cambios) == (0, 0, 151)
    assert resultado.por_estado == {"potencial": 110, "recuperado": 41}
    assert resultado.por_prioridad == {"prioritarios": 109, "no_prioritarios": 42}
    assert contar_filas(db_limpia) == 151
