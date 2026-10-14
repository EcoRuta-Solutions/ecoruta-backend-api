from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.database import get_db
from app.models.conductor import Conductor
from app.models.usuario import Usuario
from app.models.vehiculo import Vehiculo
from app.schemas.flota import (
    ConductorCreate,
    ConductorOut,
    ConductorUpdate,
    UsuarioPanelOut,
    UsuarioPanelUpdate,
    VehiculoCreate,
    VehiculoOut,
    VehiculoUpdate,
)

router = APIRouter(
    prefix="/flota",
    tags=["Flota"],
    dependencies=[Depends(require_roles("municipalidad"))],
)

_ROL_BACKEND_A_PANEL = {
    "municipalidad": "administrador",
    "conductor": "operador",
    "ciudadano": "supervisor",
}


def _a_usuario_panel(usuario: Usuario) -> UsuarioPanelOut:
    return UsuarioPanelOut(
        id=usuario.id,
        nombre=usuario.nombre,
        correo=usuario.email,
        rol=_ROL_BACKEND_A_PANEL.get(usuario.rol, "supervisor"),
        activo=usuario.activo,
    )


@router.get("/vehiculos", response_model=list[VehiculoOut])
def listar_vehiculos(db: Session = Depends(get_db)):
    return db.query(Vehiculo).order_by(Vehiculo.id).all()


@router.post("/vehiculos", response_model=VehiculoOut, status_code=status.HTTP_201_CREATED)
def crear_vehiculo(datos: VehiculoCreate, db: Session = Depends(get_db)):
    existe = db.query(Vehiculo).filter(Vehiculo.placa == datos.placa).first()
    if existe:
        raise HTTPException(status_code=409, detail="Ya existe un vehículo con esa placa")

    vehiculo = Vehiculo(**datos.model_dump())
    db.add(vehiculo)
    db.commit()
    db.refresh(vehiculo)
    return vehiculo


@router.patch("/vehiculos/{vehiculo_id}", response_model=VehiculoOut)
def actualizar_vehiculo(
    vehiculo_id: int, datos: VehiculoUpdate, db: Session = Depends(get_db)
):
    vehiculo = db.get(Vehiculo, vehiculo_id)
    if vehiculo is None:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")

    cambios = datos.model_dump(exclude_unset=True)
    placa = cambios.get("placa")
    if placa and placa != vehiculo.placa:
        duplicado = db.query(Vehiculo).filter(Vehiculo.placa == placa).first()
        if duplicado:
            raise HTTPException(
                status_code=409, detail="Ya existe un vehículo con esa placa"
            )

    for campo, valor in cambios.items():
        setattr(vehiculo, campo, valor)
    db.commit()
    db.refresh(vehiculo)
    return vehiculo


@router.get("/conductores", response_model=list[ConductorOut])
def listar_conductores(db: Session = Depends(get_db)):
    return db.query(Conductor).order_by(Conductor.id).all()


@router.post(
    "/conductores", response_model=ConductorOut, status_code=status.HTTP_201_CREATED
)
def crear_conductor(datos: ConductorCreate, db: Session = Depends(get_db)):
    if datos.vehiculo_id is not None and db.get(Vehiculo, datos.vehiculo_id) is None:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")

    conductor = Conductor(**datos.model_dump())
    db.add(conductor)
    db.commit()
    db.refresh(conductor)
    return conductor


@router.patch("/conductores/{conductor_id}", response_model=ConductorOut)
def actualizar_conductor(
    conductor_id: int, datos: ConductorUpdate, db: Session = Depends(get_db)
):
    conductor = db.get(Conductor, conductor_id)
    if conductor is None:
        raise HTTPException(status_code=404, detail="Conductor no encontrado")

    cambios = datos.model_dump(exclude_unset=True)
    vehiculo_id = cambios.get("vehiculo_id")
    if vehiculo_id is not None and db.get(Vehiculo, vehiculo_id) is None:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")

    for campo, valor in cambios.items():
        setattr(conductor, campo, valor)
    db.commit()
    db.refresh(conductor)
    return conductor


@router.get("/usuarios", response_model=list[UsuarioPanelOut])
def listar_usuarios_panel(db: Session = Depends(get_db)):
    usuarios = db.query(Usuario).order_by(Usuario.id).all()
    return [_a_usuario_panel(u) for u in usuarios]


@router.post("/usuarios", response_model=UsuarioPanelOut, status_code=status.HTTP_201_CREATED)
def crear_usuario_panel(datos: UsuarioPanelUpdate, db: Session = Depends(get_db)):
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="La creación de usuarios se hace desde el módulo de autenticación.",
    )


@router.patch("/usuarios/{usuario_id}", response_model=UsuarioPanelOut)
def actualizar_usuario_panel(
    usuario_id: int, datos: UsuarioPanelUpdate, db: Session = Depends(get_db)
):
    usuario = db.get(Usuario, usuario_id)
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if datos.nombre is not None:
        usuario.nombre = datos.nombre
    if datos.activo is not None:
        usuario.activo = datos.activo
    # El rol se acepta en el cuerpo pero se ignora a propósito: no se cambia desde este endpoint.
    db.commit()
    db.refresh(usuario)
    return _a_usuario_panel(usuario)
