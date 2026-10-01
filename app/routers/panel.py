from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, aliased

from app.database import get_db
from app.models.nodo import Nodo
from app.models.lectura import Lectura
from app.schemas.panel import NodoEstado, Resumen
from app.core.estado_nodo import calcular_estado

router = APIRouter(prefix="/panel", tags=["Panel"])


def obtener_estados(db: Session) -> list[NodoEstado]:
    # Subconsulta: la lectura más reciente de cada nodo
    ultimas = (
        db.query(Lectura)
        .distinct(Lectura.nodo_id)
        .order_by(Lectura.nodo_id, Lectura.timestamp.desc())
        .subquery()
    )
    ultima = aliased(Lectura, ultimas)

    filas = (
        db.query(Nodo, ultima)
        .outerjoin(ultima, ultima.nodo_id == Nodo.id)
        .order_by(Nodo.id)
        .all()
    )

    resultado = []
    for nodo, lectura in filas:
        fill = lectura.fill_pct if lectura else None
        resultado.append(
            NodoEstado(
                id=nodo.id,
                codigo=nodo.codigo,
                nombre=nodo.nombre,
                latitud=nodo.latitud,
                longitud=nodo.longitud,
                umbral_critico=nodo.umbral_critico,
                fill_pct=fill,
                tilt_alert=lectura.tilt_alert if lectura else None,
                ultima_lectura=lectura.timestamp if lectura else None,
                estado=calcular_estado(fill, nodo.umbral_critico),
            )
        )
    return resultado


@router.get("/estado", response_model=list[NodoEstado])
def estado_nodos(db: Session = Depends(get_db)):
    return obtener_estados(db)


@router.get("/criticos", response_model=list[NodoEstado])
def nodos_criticos(db: Session = Depends(get_db)):
    criticos = [n for n in obtener_estados(db) if n.estado == "critico"]
    return sorted(criticos, key=lambda n: n.fill_pct, reverse=True)


@router.get("/resumen", response_model=Resumen)
def resumen(db: Session = Depends(get_db)):
    estados = obtener_estados(db)
    con_dato = [n.fill_pct for n in estados if n.fill_pct is not None]
    return Resumen(
        total_nodos=len(estados),
        criticos=sum(n.estado == "critico" for n in estados),
        alertas=sum(n.estado == "alerta" for n in estados),
        normales=sum(n.estado == "normal" for n in estados),
        sin_datos=sum(n.estado == "sin_datos" for n in estados),
        promedio_llenado=round(sum(con_dato) / len(con_dato), 1) if con_dato else None,
    )