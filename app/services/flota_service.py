"""Lógica de flota por turnos: filtros, resumen y cambio de estado de camiones."""

from collections.abc import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Query, Session

from app.core.turnos import Turno, normalizar_turno
from app.models.camion import Camion, EstadoCamion
from app.schemas.camion import ConteoEstados, ResumenFlotaOut


class CambioEstadoInvalido(Exception):
    """El cambio pedido no tiene sentido para el estado actual del camión."""


class SinReservaDisponible(Exception):
    """No hay ningún camión en reserva en el turno del camión."""


def turno_normalizado_sql():
    """Expresión SQL equivalente a `normalizar_turno` ("Mañana" -> "manana")."""
    return func.translate(
        func.lower(func.trim(Camion.turno)), "ñÑáéíóúÁÉÍÓÚ", "nnaeiouaeiou"
    )


def filtrar_camiones(
    consulta: Query, turno: Turno | None = None, estado: EstadoCamion | None = None
) -> Query:
    if turno is not None:
        consulta = consulta.filter(turno_normalizado_sql() == turno.value)
    if estado is not None:
        consulta = consulta.filter(Camion.estado == estado.value)
    return consulta


def resumir(filas: Iterable[tuple[str, str, bool, bool, int]]) -> ResumenFlotaOut:
    """Arma el resumen a partir de filas (turno, estado, es_demo, datos_confirmados, n)."""
    por_turno = {turno: ConteoEstados() for turno in Turno}
    por_estado = ConteoEstados()
    total = sin_turno = demo = provisionales = 0

    for turno_texto, estado, es_demo, confirmados, cantidad in filas:
        total += cantidad
        demo += cantidad if es_demo else 0
        provisionales += 0 if confirmados else cantidad

        conteos = [por_estado]
        turno = normalizar_turno(turno_texto)
        if turno is None:
            sin_turno += cantidad
        else:
            conteos.append(por_turno[turno])

        for conteo in conteos:
            conteo.total += cantidad
            if estado in EstadoCamion.__members__:
                setattr(conteo, estado, getattr(conteo, estado) + cantidad)

    return ResumenFlotaOut(
        total=total,
        por_estado=por_estado,
        por_turno=por_turno,
        sin_turno_reconocido=sin_turno,
        demo=demo,
        datos_provisionales=provisionales,
    )


def resumen_flota(db: Session, incluir_demo: bool = True) -> ResumenFlotaOut:
    consulta = db.query(
        Camion.turno,
        Camion.estado,
        Camion.es_demo,
        Camion.datos_confirmados,
        func.count(Camion.id),
    ).group_by(Camion.turno, Camion.estado, Camion.es_demo, Camion.datos_confirmados)
    if not incluir_demo:
        consulta = consulta.filter(Camion.es_demo.is_(False))
    return resumir(consulta.all())


def cambiar_estado(
    db: Session, camion: Camion, nuevo_estado: EstadoCamion, activar_reserva: bool
) -> Camion | None:
    """Cambia el estado del camión y, si se pide, activa una reserva de su turno.

    Devuelve la reserva activada (o None). No hace commit: si lanza una
    excepción, no se ha modificado nada.
    """
    reserva = None
    if activar_reserva:
        if camion.estado != EstadoCamion.operativo.value:
            raise CambioEstadoInvalido(
                "Solo se puede activar una reserva en lugar de un camión operativo"
            )
        if nuevo_estado == EstadoCamion.operativo:
            raise CambioEstadoInvalido(
                "Para activar una reserva, el camión debe pasar a mantenimiento o reserva"
            )
        turno = normalizar_turno(camion.turno)
        if turno is None:
            raise CambioEstadoInvalido(
                f"El camión tiene un turno no reconocido ({camion.turno!r})"
            )

        reserva = (
            filtrar_camiones(db.query(Camion), turno, EstadoCamion.reserva)
            .filter(Camion.id != camion.id)
            .order_by(Camion.id)
            .with_for_update(skip_locked=True)
            .first()
        )
        if reserva is None:
            raise SinReservaDisponible(
                f"No hay camiones en reserva disponibles en el turno {turno.value}"
            )
        reserva.estado = EstadoCamion.operativo.value

    camion.estado = nuevo_estado.value
    return reserva
