from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.turnos import Turno
from app.database import get_db
from app.models.camion import Camion, EstadoCamion
from app.schemas.camion import (
    CambioEstadoCamion,
    CambioEstadoCamionOut,
    CamionCreate,
    CamionOut,
)
from app.services.flota_service import (
    CambioEstadoInvalido,
    SinReservaDisponible,
    cambiar_estado,
    filtrar_camiones,
)


router = APIRouter(prefix="/camiones", tags=["Camiones"])


@router.post(
    "",
    response_model=CamionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("municipalidad"))],
)
def crear_camion(
    datos: CamionCreate,
    db: Session = Depends(get_db),
):
    existe = (
        db.query(Camion)
        .filter(Camion.placa == datos.placa)
        .first()
    )

    if existe:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un camión con esa placa",
        )

    nuevo_camion = Camion(**datos.model_dump())

    db.add(nuevo_camion)
    db.commit()
    db.refresh(nuevo_camion)

    return nuevo_camion


@router.get(
    "",
    response_model=list[CamionOut],
    dependencies=[
        Depends(require_roles("municipalidad", "conductor"))
    ],
)
def listar_camiones(
    turno: Turno | None = Query(
        default=None,
        description="manana, tarde o noche (también encuentra los demo 'Mañana', 'Tarde', 'Noche')",
    ),
    estado: EstadoCamion | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return filtrar_camiones(db.query(Camion), turno, estado).all()


@router.patch(
    "/{camion_id}/estado",
    response_model=CambioEstadoCamionOut,
    dependencies=[Depends(require_roles("municipalidad"))],
)
def cambiar_estado_camion(
    camion_id: int,
    datos: CambioEstadoCamion,
    db: Session = Depends(get_db),
):
    camion = (
        db.query(Camion).filter(Camion.id == camion_id).with_for_update().first()
    )
    if camion is None:
        raise HTTPException(status_code=404, detail="Camión no encontrado")

    try:
        reserva = cambiar_estado(db, camion, datos.estado, datos.activar_reserva)
    except CambioEstadoInvalido as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SinReservaDisponible as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error

    db.commit()
    db.refresh(camion)
    if reserva is not None:
        db.refresh(reserva)
    return CambioEstadoCamionOut(
        camion=CamionOut.model_validate(camion),
        reserva_activada=CamionOut.model_validate(reserva) if reserva else None,
    )
