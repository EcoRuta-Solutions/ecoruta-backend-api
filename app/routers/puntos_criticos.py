from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.database import get_db
from app.models.punto_critico import EstadoPuntoCritico, PuntoCritico
from app.schemas.punto_critico import (
    PuntoCriticoOut,
    PuntosCriticosPagina,
    ResumenPuntosCriticos,
)

LIMITE_MAXIMO = 200

router = APIRouter(
    prefix="/puntos-criticos",
    tags=["Puntos críticos"],
    dependencies=[Depends(require_roles("municipalidad", "conductor"))],
)

# Columnas de salida: lat/lon salen como números con ST_Y/ST_X, nunca como WKB.
COLUMNAS = (
    PuntoCritico.id,
    PuntoCritico.codigo_unico.label("codigo"),
    PuntoCritico.estado,
    PuntoCritico.priorizacion_obligatoria,
    PuntoCritico.direccion,
    PuntoCritico.referencia,
    func.ST_Y(PuntoCritico.ubicacion).label("lat"),
    func.ST_X(PuntoCritico.ubicacion).label("lon"),
    PuntoCritico.este_utm17s,
    PuntoCritico.norte_utm17s,
    PuntoCritico.creado_en,
)


def parsear_bbox(bbox: str) -> tuple[float, float, float, float]:
    """Convierte "min_lon,min_lat,max_lon,max_lat" en floats; 422 si no es válido."""
    error = HTTPException(
        status_code=422,
        detail="bbox debe ser min_lon,min_lat,max_lon,max_lat con min < max",
    )
    partes = bbox.split(",")
    if len(partes) != 4:
        raise error
    try:
        min_lon, min_lat, max_lon, max_lat = (float(p) for p in partes)
    except ValueError:
        raise error
    if not (
        -180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90
    ):
        raise error
    return min_lon, min_lat, max_lon, max_lat


@router.get("", response_model=PuntosCriticosPagina)
def listar_puntos_criticos(
    estado: EstadoPuntoCritico | None = None,
    prioridad: bool | None = Query(
        default=None, description="Filtra por priorización obligatoria"
    ),
    bbox: str | None = Query(
        default=None,
        description="min_lon,min_lat,max_lon,max_lat (WGS84)",
        examples=["-79.04,-8.12,-79.02,-8.10"],
    ),
    limit: int = Query(default=50, ge=1, le=LIMITE_MAXIMO),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    filtros = []
    if estado is not None:
        filtros.append(PuntoCritico.estado == estado)
    if prioridad is not None:
        filtros.append(PuntoCritico.priorizacion_obligatoria == prioridad)
    if bbox is not None:
        caja = func.ST_MakeEnvelope(*parsear_bbox(bbox), 4326)
        filtros.append(func.ST_Intersects(PuntoCritico.ubicacion, caja))

    total = db.scalar(
        select(func.count()).select_from(PuntoCritico).where(*filtros)
    )
    filas = db.execute(
        select(*COLUMNAS)
        .where(*filtros)
        .order_by(PuntoCritico.id)
        .limit(limit)
        .offset(offset)
    ).all()

    return PuntosCriticosPagina(
        total=total,
        limit=limit,
        offset=offset,
        items=[PuntoCriticoOut.model_validate(fila) for fila in filas],
    )


# Va antes de /{codigo} para que "resumen" no se tome como un código.
@router.get("/resumen", response_model=ResumenPuntosCriticos)
def resumen_puntos_criticos(db: Session = Depends(get_db)):
    por_estado = dict(
        db.execute(
            select(PuntoCritico.estado, func.count()).group_by(
                PuntoCritico.estado
            )
        ).all()
    )
    por_prioridad = dict(
        db.execute(
            select(PuntoCritico.priorizacion_obligatoria, func.count()).group_by(
                PuntoCritico.priorizacion_obligatoria
            )
        ).all()
    )

    return ResumenPuntosCriticos(
        total=sum(por_estado.values()),
        por_estado={e.value: por_estado.get(e, 0) for e in EstadoPuntoCritico},
        por_prioridad={
            "prioritarios": por_prioridad.get(True, 0),
            "no_prioritarios": por_prioridad.get(False, 0),
        },
    )


@router.get("/{codigo}", response_model=PuntoCriticoOut)
def detalle_punto_critico(codigo: str, db: Session = Depends(get_db)):
    fila = db.execute(
        select(*COLUMNAS).where(PuntoCritico.codigo_unico == codigo)
    ).first()

    if fila is None:
        raise HTTPException(
            status_code=404,
            detail="Punto crítico no encontrado",
        )

    return PuntoCriticoOut.model_validate(fila)
