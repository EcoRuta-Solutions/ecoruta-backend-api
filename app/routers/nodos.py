from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.database import get_db
from app.models.nodo import Nodo
from app.models.lectura import Lectura
from app.schemas.nodo import NodoCreate, NodoOut
from app.schemas.prediccion import PrediccionOut
from app.schemas.optimizacion import RutaOptimizadaOut
from app.services.prediccion_service import estimar_horas_critico
from app.services.optimizador_service import optimizar_con_ortools


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
        raise HTTPException(
            status_code=409,
            detail="Ya existe un nodo con ese código",
        )

    nodo = Nodo(**datos.model_dump())
    db.add(nodo)
    db.commit()
    db.refresh(nodo)

    return nodo


@router.get(
    "/optimizar",
    response_model=RutaOptimizadaOut,
    dependencies=[Depends(require_roles("municipalidad", "conductor"))],
)
def optimizar_ruta(
    inicio_id: int | None = None,
    db: Session = Depends(get_db),
):
    nodos = db.query(Nodo).order_by(Nodo.id).all()

    if not nodos:
        return {
            "inicio_id": 0,
            "ruta": [],
            "cantidad_nodos": 0,
        }

    indice_inicio = 0

    if inicio_id is not None:
        for indice, nodo in enumerate(nodos):
            if nodo.id == inicio_id:
                indice_inicio = indice
                break
        else:
            raise HTTPException(
                status_code=404,
                detail="Nodo de inicio no encontrado",
            )

    ruta = optimizar_con_ortools(
        nodos,
        indice_inicio=indice_inicio,
    )

    return {
        "inicio_id": nodos[indice_inicio].id,
        "ruta": ruta,
        "cantidad_nodos": len(ruta),
    }


@router.get(
    "/{nodo_id}/prediccion",
    response_model=PrediccionOut,
)
def prediccion_nodo(
    nodo_id: int,
    db: Session = Depends(get_db),
    _usuario=Depends(require_roles("municipalidad", "conductor")),
):
    nodo = db.get(Nodo, nodo_id)

    if nodo is None:
        raise HTTPException(
            status_code=404,
            detail="Nodo no encontrado",
        )

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
