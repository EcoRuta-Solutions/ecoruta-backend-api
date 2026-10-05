from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import require_roles, verify_device_key
from app.database import get_db
from app.models.nodo import Nodo
from app.models.lectura import Lectura
from app.schemas.lectura import LecturaCreate, LecturaOut

router = APIRouter(tags=["Lecturas"])


@router.post(
    "/lecturas/",
    response_model=LecturaOut,
    status_code=201,
    dependencies=[Depends(verify_device_key)],
)
def crear_lectura(datos: LecturaCreate, db: Session = Depends(get_db)):
    # El sensor manda el código legible; aquí lo convertimos al id numérico
    nodo = db.query(Nodo).filter(Nodo.codigo == datos.codigo).first()
    if nodo is None:
        raise HTTPException(status_code=404, detail="No existe un nodo con ese código")

    lectura = Lectura(
        nodo_id=nodo.id,
        fill_pct=datos.fill_pct,
        tilt_alert=datos.tilt_alert,
    )
    db.add(lectura)
    db.commit()
    db.refresh(lectura)
    return lectura


@router.get(
    "/nodos/{nodo_id}/lecturas",
    response_model=list[LecturaOut],
    dependencies=[Depends(require_roles("municipalidad", "conductor"))],
)
def historial_nodo(nodo_id: int, limite: int = 100, db: Session = Depends(get_db)):
    nodo = db.get(Nodo, nodo_id)
    if nodo is None:
        raise HTTPException(status_code=404, detail="Nodo no encontrado")

    return (
        db.query(Lectura)
        .filter(Lectura.nodo_id == nodo_id)
        .order_by(Lectura.timestamp.desc())
        .limit(limite)
        .all()
    )