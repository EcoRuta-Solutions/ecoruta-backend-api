from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.database import get_db
from app.models.camion import Camion
from app.schemas.camion import CamionCreate, CamionOut

router = APIRouter(prefix="/camiones", tags=["Camiones"])

@router.post("", response_model=CamionOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles("municipalidad"))])
def crear_camion(camion: CamionCreate, db: Session = Depends(get_db)):
    existe = db.query(Camion).filter(Camion.placa == datos.placa).first()
    if existe:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe un camión con esa placa",)

    camion = Camion(**datos.model_dump())
    db.add(camion)
    db.commit()
    db.refresh(camion)
    return camion

@router.get("", response_model=List[CamionOut], dependencies=[Depends(require_roles("municipalidad", "conductor"))],)
def listar_camiones(db: Session = Depends(get_db)):
    return db.query(Camion).all()