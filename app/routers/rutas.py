
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.deps import require_roles
from app.database import get_db
from app.models.camion import Camion
from app.models.nodo import Nodo
from app.models.ruta import Parada, Ruta
from app.schemas.ruta import RutaCreate, RutaOut


router = APIRouter(prefix="/rutas", tags=["Rutas"])


@router.post(
    "",
    response_model=RutaOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("municipalidad"))],
)
def crear_ruta(
    datos: RutaCreate,
    db: Session = Depends(get_db),
):
    camion = db.get(Camion, datos.camion_id)

    if camion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camión no encontrado",
        )

    if datos.fecha_fin < datos.fecha_inicio:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La fecha de fin no puede ser anterior a la fecha de inicio",
        )

    if datos.hora_fin < datos.hora_inicio:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La hora de fin no puede ser anterior a la hora de inicio",
        )

    ordenes = [parada.orden for parada in datos.paradas]

    if len(ordenes) != len(set(ordenes)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El orden de las paradas no puede repetirse",
        )

    for parada in datos.paradas:
        nodo = db.get(Nodo, parada.nodo_id)

        if nodo is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No existe el nodo {parada.nodo_id}",
            )

    nueva_ruta = Ruta(
        fecha_inicio=datos.fecha_inicio,
        fecha_fin=datos.fecha_fin,
        hora_inicio=datos.hora_inicio,
        hora_fin=datos.hora_fin,
        camion_id=datos.camion_id,
        estado="Pendiente",
    )

    try:
        db.add(nueva_ruta)
        db.flush()

        for parada in datos.paradas:
            nueva_parada = Parada(
                ruta_id=nueva_ruta.id,
                nodo_id=parada.nodo_id,
                orden=parada.orden,
            )
            db.add(nueva_parada)

        db.commit()
        db.refresh(nueva_ruta)

    except Exception:
        db.rollback()
        raise

    return nueva_ruta


@router.get(
    "/hoy",
    response_model=list[RutaOut],
    dependencies=[
        Depends(require_roles("municipalidad", "conductor"))
    ],
)
def rutas_del_dia(db: Session = Depends(get_db)):
    hoy = date.today()

    return (
        db.query(Ruta)
        .options(
            joinedload(Ruta.camion),
            selectinload(Ruta.paradas),
        )
        .filter(Ruta.fecha_inicio == hoy)
        .order_by(Ruta.id)
        .all()
    )

