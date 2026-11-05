from datetime import UTC, time

import pytest

from app.core.turnos import Turno, hora_en_turno, normalizar_turno, turno_de_hora
from app.services.flota_service import resumir


def test_horarios_de_los_turnos():
    assert (Turno.manana.inicio, Turno.manana.fin) == (time(5), time(13))
    assert (Turno.tarde.inicio, Turno.tarde.fin) == (time(13), time(21))
    assert (Turno.noche.inicio, Turno.noche.fin) == (time(21), time(5))
    assert Turno.noche.cruza_medianoche
    assert not Turno.manana.cruza_medianoche
    assert not Turno.tarde.cruza_medianoche


@pytest.mark.parametrize(
    ("hora", "turno"),
    [
        (time(5, 0), Turno.manana),
        (time(9, 30), Turno.manana),
        (time(12, 59, 59), Turno.manana),
        (time(13, 0), Turno.tarde),
        (time(20, 59), Turno.tarde),
        (time(21, 0), Turno.noche),
        (time(23, 59, 59), Turno.noche),
        (time(0, 0), Turno.noche),
        (time(3, 15), Turno.noche),
        (time(4, 59, 59), Turno.noche),
    ],
)
def test_cada_hora_cae_en_un_solo_turno(hora, turno):
    assert turno_de_hora(hora) == turno
    assert [t for t in Turno if hora_en_turno(hora, t)] == [turno]


def test_noche_cruza_medianoche():
    assert Turno.noche.incluye(time(23, 0))
    assert Turno.noche.incluye(time(0, 0))
    assert Turno.noche.incluye(time(4, 0))
    assert not Turno.noche.incluye(time(5, 0))
    assert not Turno.noche.incluye(time(12, 0))
    assert not Turno.noche.incluye(time(20, 59))


def test_hora_con_zona_horaria_se_compara_como_hora_local():
    assert Turno.manana.incluye(time(6, 0, tzinfo=UTC))


@pytest.mark.parametrize(
    ("texto", "turno"),
    [
        ("manana", Turno.manana),
        ("Mañana", Turno.manana),
        ("  MAÑANA ", Turno.manana),
        ("Tarde", Turno.tarde),
        ("noche", Turno.noche),
        ("Madrugada", None),
        ("", None),
        (None, None),
    ],
)
def test_normalizar_turno_acepta_formato_demo_y_nuevo(texto, turno):
    assert normalizar_turno(texto) == turno


def test_resumir_cuenta_por_turno_y_estado():
    resumen = resumir(
        [
            ("manana", "operativo", False, False, 13),
            ("manana", "reserva", False, False, 3),
            ("Mañana", "operativo", True, False, 1),
            ("noche", "mantenimiento", False, True, 2),
            ("Madrugada", "operativo", False, False, 1),
        ]
    )

    assert resumen.total == 20
    assert resumen.por_turno[Turno.manana].operativo == 14
    assert resumen.por_turno[Turno.manana].reserva == 3
    assert resumen.por_turno[Turno.manana].total == 17
    assert resumen.por_turno[Turno.tarde].total == 0
    assert resumen.por_turno[Turno.noche].mantenimiento == 2
    assert resumen.por_estado.operativo == 15
    assert resumen.sin_turno_reconocido == 1
    assert resumen.demo == 1
    assert resumen.datos_provisionales == 18
