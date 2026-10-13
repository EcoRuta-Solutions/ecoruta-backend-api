from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.database import get_db
from app.models.reporte import EstadoReporte, ReporteCiudadano
from app.models.usuario import Usuario
from app.schemas.reporte import ReporteActualizar, ReporteCrear, ReporteOut

router = APIRouter(prefix="/reportes", tags=["Reportes ciudadanos"])


@router.post("", response_model=ReporteOut, status_code=201)
def crear_reporte(
    datos: ReporteCrear,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(require_roles("ciudadano", "conductor")),
):
    reporte = ReporteCiudadano(
        usuario_id=usuario.id,
        latitud=datos.latitud,
        longitud=datos.longitud,
        descripcion=datos.descripcion,
        foto_url=str(datos.foto_url) if datos.foto_url else None,
    )
    db.add(reporte)
    db.commit()
    db.refresh(reporte)
    return reporte


@router.get("", response_model=list[ReporteOut])
def listar_reportes(
    estado: EstadoReporte | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_roles("municipalidad")),
):
    consulta = db.query(ReporteCiudadano)
    if estado is not None:
        consulta = consulta.filter(ReporteCiudadano.estado == estado.value)
    return (
        consulta.order_by(ReporteCiudadano.timestamp.desc(), ReporteCiudadano.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/mios", response_model=list[ReporteOut])
def listar_mis_reportes(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    return (
        db.query(ReporteCiudadano)
        .filter(ReporteCiudadano.usuario_id == usuario.id)
        .order_by(ReporteCiudadano.timestamp.desc(), ReporteCiudadano.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.patch("/{reporte_id}", response_model=ReporteOut)
def actualizar_reporte(
    reporte_id: int,
    datos: ReporteActualizar,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_roles("municipalidad")),
):
    reporte = db.get(ReporteCiudadano, reporte_id)
    if reporte is None:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")

    cambios = False
    if reporte.estado != datos.estado:
        reporte.estado = datos.estado
        cambios = True
    if datos.asignado_a is not None and datos.asignado_a != reporte.asignado_a:
        reporte.asignado_a = datos.asignado_a
        cambios = True

    if cambios:
        db.commit()
        db.refresh(reporte)
    return reporte