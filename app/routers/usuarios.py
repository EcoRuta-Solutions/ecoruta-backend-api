from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.database import get_db
from app.models.usuario import Usuario
from app.schemas.usuario import UsuarioOut


router = APIRouter(prefix="/usuarios", tags=["Usuarios"])


@router.get(
    "/conductores",
    response_model=list[UsuarioOut],
    dependencies=[Depends(require_roles("municipalidad", "conductor"))],
)
def listar_conductores(db: Session = Depends(get_db)):
    """Conductores activos, para asignarlos al generar una ruta."""
    return (
        db.query(Usuario)
        .filter(Usuario.rol == "conductor", Usuario.activo.is_(True))
        .order_by(Usuario.id)
        .all()
    )
