from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import require_roles
from app.models.nodo import Nodo
from app.models.lectura import Lectura
from app.schemas.nodo import NodoCreate, NodoOut
from app.schemas.prediccion import PrediccionOut
from app.services.prediccion_service import estimar_horas_critico

router = APIRouter(prefix="/nodos", tags=["Nodos"])


@router.get("/", response_model=list[NodoOut])
def listar_nodos(db: Session = Depends(get_db)):
    return db.query(Nodo).all()


@router.post("/", response_model=NodoOut, status_code=201)
def crear_nodo(datos: NodoCreate, db: Session = Depends(get_db)):
    existe = db.query(Nodo).filter(Nodo.codigo == datos.codigo).first()
    if existe:
        raise HTTPException(status_code=409, detail="Ya existe un nodo con ese código")

    nodo = Nodo(**datos.model_dump())
    db.add(nodo)
    db.commit()
    db.refresh(nodo)
    return nodo


@router.get("/{nodo_id}/prediccion", response_model=PrediccionOut)
def prediccion_nodo(
    nodo_id: int,
    db: Session = Depends(get_db),
    _usuario=Depends(require_roles("municipalidad", "conductor")),
):
    nodo = db.get(Nodo, nodo_id)
    if nodo is None:
        raise HTTPException(status_code=404, detail="Nodo no encontrado")

    lecturas = (
        db.query(Lectura)
        .filter(Lectura.nodo_id == nodo_id)
        .order_by(Lectura.timestamp.asc(), Lectura.id.asc())
        .all()
    )
    estimacion = estimar_horas_critico(nodo, lecturas)
    return PrediccionOut(
        nodo_id=nodo.id,
        codigo=nodo.codigo,
        umbral_critico=nodo.umbral_critico,
        **estimacion,
    )