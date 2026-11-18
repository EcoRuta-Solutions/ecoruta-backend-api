from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.database import get_db
from app.models.alerta import Alerta
from app.models.punto_critico import PuntoCritico
from app.schemas.alerta import AlertaOut

router = APIRouter(
    prefix="/alertas",
    tags=["Alertas"],
    dependencies=[Depends(require_roles("municipalidad", "conductor"))],
)


@router.get("/activas", response_model=list[AlertaOut])
def alertas_activas(db: Session = Depends(get_db)):
    """Alertas sin resolver, de la más reciente a la más antigua (solo lectura)."""
    filas = db.execute(
        select(
            Alerta.id,
            Alerta.tipo,
            Alerta.mensaje,
            Alerta.nivel_pct,
            Alerta.punto_critico_id,
            PuntoCritico.codigo_unico.label("punto_codigo"),
            PuntoCritico.direccion,
            func.ST_Y(PuntoCritico.ubicacion).label("lat"),
            func.ST_X(PuntoCritico.ubicacion).label("lon"),
            Alerta.creada_en,
        )
        .join(PuntoCritico, PuntoCritico.id == Alerta.punto_critico_id)
        .where(Alerta.activa.is_(True))
        .order_by(Alerta.creada_en.desc(), Alerta.id.desc())
    ).mappings()
    return [AlertaOut(**fila) for fila in filas]
