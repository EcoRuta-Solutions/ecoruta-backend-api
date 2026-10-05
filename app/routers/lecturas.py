from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import require_roles, verify_device_key
from app.database import get_db
from app.models.nodo import Nodo
from app.models.lectura import Lectura
from app.schemas.lectura import LecturaCreate, LecturaOut
from app.core.connection_manager import connection_manager
from app.core.estado_nodo import calcular_estado

router = APIRouter(tags=["Lecturas"])


@router.post(
    "/lecturas/",
    response_model=LecturaOut,
    status_code=201,
    dependencies=[Depends(verify_device_key)],
)
def crear_lectura(
    datos: LecturaCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    # El sensor manda el código legible; aquí lo convertimos al id numérico
    nodo = db.query(Nodo).filter(Nodo.codigo == datos.codigo).first()
    if nodo is None:
        raise HTTPException(status_code=404, detail="No existe un nodo con ese código")

    lectura_anterior = (
        db.query(Lectura)
        .filter(Lectura.nodo_id == nodo.id)
        .order_by(Lectura.timestamp.desc(), Lectura.id.desc())
        .first()
    )
    estado_anterior = calcular_estado(
        lectura_anterior.fill_pct if lectura_anterior else None,
        nodo.umbral_critico,
    )
    lectura = Lectura(
        nodo_id=nodo.id,
        fill_pct=datos.fill_pct,
        tilt_alert=datos.tilt_alert,
    )
    db.add(lectura)
    db.commit()
    db.refresh(lectura)

    estado_actual = calcular_estado(lectura.fill_pct, nodo.umbral_critico)
    evento = {
        "tipo": "lectura_nueva",
        "nodo_id": nodo.id,
        "codigo": nodo.codigo,
        "fill_pct": lectura.fill_pct,
        "estado": estado_actual,
        "tilt_alert": lectura.tilt_alert,
        "timestamp": lectura.timestamp.isoformat(),
    }
    background_tasks.add_task(connection_manager.broadcast, evento)
    if estado_actual != estado_anterior:
        background_tasks.add_task(
            connection_manager.broadcast,
            {**evento, "tipo": "estado_cambiado"},
        )
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