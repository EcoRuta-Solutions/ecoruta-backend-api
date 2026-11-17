"""Reportes de campo: último reporte por punto, vigencia y distancia al punto.

El estado de llenado de un punto crítico sale SOLO de su último reporte de campo
vigente. Si no hay uno vigente, el punto está "sin_datos": nunca se supone un valor.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.models.punto_critico import PuntoCritico
from app.models.reporte_campo import EstadoReporte, ReporteCampo
from app.models.usuario import Usuario

SIN_DATOS = "sin_datos"


def vigencia() -> timedelta:
    return timedelta(hours=config.REPORTE_VIGENCIA_HORAS)


def ahora() -> datetime:
    return datetime.now(timezone.utc)


def es_vigente(creado_en: datetime | None, momento: datetime | None = None) -> bool:
    """True si el reporte tiene menos de REPORTE_VIGENCIA_HORAS."""
    if creado_en is None:
        return False
    return (momento or ahora()) - creado_en < vigencia()


def estado_llenado(
    estado: EstadoReporte | str | None,
    creado_en: datetime | None,
    momento: datetime | None = None,
) -> str:
    """Estado a mostrar: el del último reporte si está vigente; si no, "sin_datos"."""
    if estado is None or not es_vigente(creado_en, momento):
        return SIN_DATOS
    return EstadoReporte(estado).value


def ultimo_reporte_por_punto():
    """Subconsulta con el último reporte no demo de cada punto (DISTINCT ON)."""
    return (
        select(
            ReporteCampo.punto_critico_id,
            ReporteCampo.id.label("reporte_id"),
            ReporteCampo.estado,
            ReporteCampo.creado_en,
        )
        .where(ReporteCampo.es_demo.is_(False))
        .distinct(ReporteCampo.punto_critico_id)
        .order_by(
            ReporteCampo.punto_critico_id,
            ReporteCampo.creado_en.desc(),
            ReporteCampo.id.desc(),
        )
        .subquery("ultimo_reporte")
    )


def distancia_al_punto(db: Session, punto_id: int, lat: float, lon: float) -> float:
    """Distancia en metros (geodésica, PostGIS geography) del dispositivo al punto."""
    dispositivo = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
    return db.scalar(
        select(
            func.ST_Distance(
                func.geography(PuntoCritico.ubicacion), func.geography(dispositivo)
            )
        ).where(PuntoCritico.id == punto_id)
    )


def esta_lejos(distancia_m: float | None) -> bool:
    return distancia_m is not None and distancia_m > config.REPORTE_DISTANCIA_MAX_M


def resumen_por_estado(db: Session, momento: datetime | None = None) -> dict:
    """Cuenta puntos críticos por estado de su último reporte vigente, y los sin datos."""
    ultimo = ultimo_reporte_por_punto()
    filas = db.execute(
        select(ultimo.c.estado, ultimo.c.creado_en)
        .select_from(PuntoCritico)
        .outerjoin(ultimo, ultimo.c.punto_critico_id == PuntoCritico.id)
    ).all()

    momento = momento or ahora()
    por_estado = {e.value: 0 for e in EstadoReporte}
    sin_datos = 0
    for estado, creado_en in filas:
        valor = estado_llenado(estado, creado_en, momento)
        if valor == SIN_DATOS:
            sin_datos += 1
        else:
            por_estado[valor] += 1

    return {
        "total_puntos": len(filas),
        "vigencia_horas": config.REPORTE_VIGENCIA_HORAS,
        "por_estado": por_estado,
        "sin_datos": sin_datos,
    }


def consulta_reportes():
    """SELECT de reportes con el código del punto y el nombre de quien reportó."""
    return (
        select(
            ReporteCampo.id,
            ReporteCampo.punto_critico_id,
            PuntoCritico.codigo_unico.label("codigo_punto"),
            ReporteCampo.usuario_id,
            Usuario.nombre.label("usuario_nombre"),
            ReporteCampo.estado,
            ReporteCampo.observacion,
            ReporteCampo.lat,
            ReporteCampo.lon,
            ReporteCampo.distancia_m,
            ReporteCampo.lejos_del_punto,
            ReporteCampo.foto_url,
            ReporteCampo.creado_en,
            ReporteCampo.es_demo,
        )
        .join(PuntoCritico, PuntoCritico.id == ReporteCampo.punto_critico_id)
        .join(Usuario, Usuario.id == ReporteCampo.usuario_id)
    )
