from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.database import get_db
from app.models.nodo import Nodo
from app.schemas.nodo import NodoCreate, NodoOut

router = APIRouter(prefix="/nodos", tags=["Nodos"])


@router.get(
    "/",
    response_model=list[NodoOut],
    dependencies=[Depends(require_roles("municipalidad", "conductor"))],
)
def listar_nodos(db: Session = Depends(get_db)):
    return db.query(Nodo).all()


@router.post(
    "/",
    response_model=NodoOut,
    status_code=201,
    dependencies=[Depends(require_roles("municipalidad"))],
)
def crear_nodo(datos: NodoCreate, db: Session = Depends(get_db)):
    existe = db.query(Nodo).filter(Nodo.codigo == datos.codigo).first()
    if existe:
        raise HTTPException(status_code=409, detail="Ya existe un nodo con ese código")

    nodo = Nodo(**datos.model_dump())
    db.add(nodo)
    db.commit()
    db.refresh(nodo)
    return nodo