from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.database import get_db
from app.models.punto_critico import PuntoCritico
from app.models.reporte_campo import ReporteCampo
from app.models.usuario import Usuario
from app.schemas.reporte_campo import (
    ReporteCampoCreate,
    ReporteCampoOut,
    ReportesCampoPagina,
    ResumenReportesOut,
)
from app.services import reportes_service

LIMITE_MAXIMO = 200

router = APIRouter(
    prefix="/reportes-campo",
    tags=["Reportes de campo"],
    dependencies=[Depends(require_roles("municipalidad", "conductor"))],
)


@router.post("", response_model=ReporteCampoOut, status_code=status.HTTP_201_CREATED)
def crear_reporte(
    datos: ReporteCampoCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(require_roles("municipalidad", "conductor")),
):
    """Registra el nivel de llenado observado en un punto crítico.

    El usuario sale del token. Si llegan lat/lon se calcula la distancia al punto;
    si supera REPORTE_DISTANCIA_MAX_M se marca lejos_del_punto, pero se guarda igual.
    """
    punto_id = db.scalar(
        select(PuntoCritico.id).where(PuntoCritico.codigo_unico == datos.codigo_punto.strip())
    )
    if punto_id is None:
        raise HTTPException(status_code=404, detail="Punto crítico no encontrado")

    distancia = None
    if datos.lat is not None and datos.lon is not None:
        distancia = reportes_service.distancia_al_punto(db, punto_id, datos.lat, datos.lon)

    reporte = ReporteCampo(
        punto_critico_id=punto_id,
        usuario_id=usuario.id,
        estado=datos.estado,
        observacion=(datos.observacion or "").strip() or None,
        lat=datos.lat,
        lon=datos.lon,
        distancia_m=distancia,
        lejos_del_punto=reportes_service.esta_lejos(distancia),
        # Lo que reporta una cuenta demo no cuenta como dato real.
        es_demo=bool(usuario.es_demo),
    )
    db.add(reporte)
    db.commit()

    fila = db.execute(
        reportes_service.consulta_reportes().where(ReporteCampo.id == reporte.id)
    ).one()
    return ReporteCampoOut.model_validate(fila)


@router.get("", response_model=ReportesCampoPagina)
def listar_reportes(
    punto: str | None = Query(default=None, description="Código del punto crítico"),
    desde: datetime | None = Query(default=None, description="Desde (ISO 8601, inclusivo)"),
    hasta: datetime | None = Query(default=None, description="Hasta (ISO 8601, exclusivo)"),
    incluir_demo: bool = Query(
        default=False, description="Incluir reportes de cuentas demo (depuración)"
    ),
    limit: int = Query(default=50, ge=1, le=LIMITE_MAXIMO),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Reportes de campo, del más reciente al más antiguo."""
    if desde is not None and hasta is not None and desde >= hasta:
        raise HTTPException(status_code=422, detail="desde debe ser anterior a hasta")

    filtros = []
    if punto is not None:
        filtros.append(PuntoCritico.codigo_unico == punto.strip())
    if desde is not None:
        filtros.append(ReporteCampo.creado_en >= desde)
    if hasta is not None:
        filtros.append(ReporteCampo.creado_en < hasta)
    if not incluir_demo:
        filtros.append(ReporteCampo.es_demo.is_(False))

    total = db.scalar(
        select(func.count())
        .select_from(ReporteCampo)
        .join(PuntoCritico, PuntoCritico.id == ReporteCampo.punto_critico_id)
        .where(*filtros)
    )
    filas = db.execute(
        reportes_service.consulta_reportes()
        .where(*filtros)
        .order_by(ReporteCampo.creado_en.desc(), ReporteCampo.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return ReportesCampoPagina(
        total=total,
        limit=limit,
        offset=offset,
        items=[ReporteCampoOut.model_validate(f) for f in filas],
    )


@router.get("/resumen", response_model=ResumenReportesOut)
def resumen_reportes(db: Session = Depends(get_db)):
    """Puntos críticos por estado de su último reporte vigente y cuántos están sin datos."""
    return reportes_service.resumen_por_estado(db)
