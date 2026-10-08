from datetime import date
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.database import get_db
from app.models.camion import Camion
from app.models.ruta import Parada, Ruta
from app.schemas.usuario import Usuario
from app.schemas.ruta import RutaCreate, RutaOut

router = APIRouter(prefix="/rutas", tags=["Rutas"])

@router.post("", response_model=RutaOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles("municipalidad"))],)
def crear_ruta(ruta: RutaCreate, db: Session = Depends(get_db)):
    camion = db.get(Camion, datos.camion_id)
    if not camion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camión no encontrado")

    nueva_ruta = Ruta(
        fecha=date.fecha, camion_id = datos.camion, estado="pendiente"()
    )
    db.add(nueva_ruta)
    db.commit()
    db.refresh(nueva_ruta)

    for parada in datos.paradas:
        p = Parada(
            ruta_id=nueva_ruta.id,
            nodo_id=parada.nodo_id,
            orden=parada.orden,
            hora_estimada=parada.hora_estimada,
        )
        db.add(p)

    db.commit()
    db.refresh(nueva_ruta)
    return nueva_ruta

@router.get("hoy", response_model=List[RutaOut],)
def ruta_del_dia(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(require_roles("conductor")),
):
    hoy = date.today()
    rutas = db.query(Ruta).filter(Ruta.fecha == hoy).all()
    return rutas
