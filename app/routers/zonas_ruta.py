import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.turnos import normalizar_turno
from app.database import get_db
from app.models.zona_ruta import ZonaRuta
from app.schemas.zona_ruta import ZonaRutaOut

router = APIRouter(
    prefix="/zonas-ruta",
    tags=["Zonas de ruta"],
    dependencies=[Depends(require_roles("municipalidad", "conductor"))],
)

_PATRON_CODIGO = re.compile(r"^([A-Za-z]+)-?(\d+)$")


def _clave_orden(zona: ZonaRuta):
    """Ordena por código natural (M-2 antes que M-10) y luego por tramo."""
    coincidencia = _PATRON_CODIGO.match(zona.codigo)
    codigo = (
        (coincidencia.group(1).upper(), int(coincidencia.group(2)))
        if coincidencia
        else (zona.codigo, 0)
    )
    return codigo, zona.tramo


@router.get("", response_model=list[ZonaRutaOut])
def listar_zonas_ruta(
    turno: str | None = Query(
        default=None, description="manana (o mañana), tarde o noche"
    ),
    db: Session = Depends(get_db),
):
    """Una fila por tramo, ordenada por código de ruta y tramo."""
    consulta = db.query(ZonaRuta)
    if turno is not None:
        turno_normalizado = normalizar_turno(turno)
        if turno_normalizado is None:
            raise HTTPException(
                status_code=422,
                detail="turno debe ser manana, tarde o noche",
            )
        consulta = consulta.filter(ZonaRuta.turno == turno_normalizado.value)

    return sorted(consulta.all(), key=_clave_orden)


@router.get("/{codigo}", response_model=list[ZonaRutaOut])
def tramos_de_zona_ruta(codigo: str, db: Session = Depends(get_db)):
    """Todos los tramos de una ruta, en orden de tramo."""
    tramos = (
        db.query(ZonaRuta)
        .filter(ZonaRuta.codigo == codigo.strip().upper())
        .order_by(ZonaRuta.tramo)
        .all()
    )
    if not tramos:
        raise HTTPException(status_code=404, detail="Zona de ruta no encontrada")
    return tramos
