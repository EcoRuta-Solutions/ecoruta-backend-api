from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.database import get_db
from app.models.camion import Camion
from app.models.conductor import Conductor
from app.models.usuario import Usuario
from app.schemas.camion import ResumenFlotaOut
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
from app.services import flota_service

router = APIRouter(
    prefix="/flota",
    tags=["Flota"],
    dependencies=[Depends(require_roles("municipalidad"))],
)

_ROL_BACKEND_A_PANEL = {
    "municipalidad": "administrador",
    "conductor": "operador",
}


def _a_usuario_panel(usuario: Usuario) -> UsuarioPanelOut:
    return UsuarioPanelOut(
        id=usuario.id,
        nombre=usuario.nombre,
        correo=usuario.email,
        rol=_ROL_BACKEND_A_PANEL.get(usuario.rol, "supervisor"),
        activo=usuario.activo,
    )


@router.get("/resumen", response_model=ResumenFlotaOut)
def resumen_flota(
    incluir_demo: bool = Query(
        default=True, description="Incluir los camiones demo de seed_demo.py"
    ),
    db: Session = Depends(get_db),
):
    """Totales de la tabla `camiones` por turno y estado."""
    return flota_service.resumen_flota(db, incluir_demo=incluir_demo)


# --- /flota/vehiculos (obsoleto) --------------------------------------------
# Lee y escribe sobre `camiones` con el esquema de siempre. El id es el del camión.
# El frontend debe pasar a /camiones; estos endpoints se quitarán más adelante.

_NO_NULOS = ("placa", "estado", "activo")


def _aplicar_capacidad(camion: Camion, toneladas: float | None) -> None:
    """Guarda toneladas y kg (toneladas * 1000); None = por confirmar."""
    camion.capacidad_toneladas = toneladas
    camion.capacidad = round(toneladas * 1000) if toneladas is not None else None


def _placa_ocupada(db: Session, placa: str) -> bool:
    return db.query(Camion).filter(Camion.placa == placa).first() is not None


@router.get("/vehiculos", response_model=list[VehiculoOut], deprecated=True)
def listar_vehiculos(db: Session = Depends(get_db)):
    return db.query(Camion).order_by(Camion.id).all()


@router.post(
    "/vehiculos",
    response_model=VehiculoOut,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
)
def crear_vehiculo(datos: VehiculoCreate, db: Session = Depends(get_db)):
    if _placa_ocupada(db, datos.placa):
        raise HTTPException(status_code=409, detail="Ya existe un vehículo con esa placa")

    camion = Camion(
        placa=datos.placa,
        tipo=datos.tipo,
        turno=datos.turno,
        estado=datos.estado.value,
        activo=datos.activo,
        datos_confirmados=False,
        es_demo=False,
    )
    _aplicar_capacidad(camion, datos.capacidad_toneladas)
    db.add(camion)
    db.commit()
    db.refresh(camion)
    return camion


@router.patch("/vehiculos/{vehiculo_id}", response_model=VehiculoOut, deprecated=True)
def actualizar_vehiculo(
    vehiculo_id: int, datos: VehiculoUpdate, db: Session = Depends(get_db)
):
    camion = db.get(Camion, vehiculo_id)
    if camion is None:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")

    cambios = datos.model_dump(exclude_unset=True)
    nulos = [campo for campo in _NO_NULOS if campo in cambios and cambios[campo] is None]
    if nulos:
        raise HTTPException(
            status_code=422, detail=f"No pueden ser null: {', '.join(nulos)}"
        )

    placa = cambios.get("placa")
    if placa and placa != camion.placa and _placa_ocupada(db, placa):
        raise HTTPException(status_code=409, detail="Ya existe un vehículo con esa placa")

    if "capacidad_toneladas" in cambios:
        _aplicar_capacidad(camion, cambios.pop("capacidad_toneladas"))
    if "estado" in cambios:
        camion.estado = cambios.pop("estado").value
    for campo, valor in cambios.items():
        setattr(camion, campo, valor)
    db.commit()
    db.refresh(camion)
    return camion


# --- /flota/conductores ------------------------------------------------------


def _resolver_camion(db: Session, enviados: dict) -> tuple[bool, int | None]:
    """Lee camion_id y su alias vehiculo_id. Devuelve (se envió, camion_id)."""
    valores = {enviados[k] for k in ("camion_id", "vehiculo_id") if k in enviados}
    if not valores:
        return False, None
    if len(valores) > 1:
        raise HTTPException(
            status_code=422,
            detail="camion_id y vehiculo_id no coinciden (vehiculo_id es un alias de camion_id)",
        )
    camion_id = valores.pop()
    if camion_id is not None and db.get(Camion, camion_id) is None:
        raise HTTPException(status_code=404, detail="Camión no encontrado")
    return True, camion_id


def _a_conductor_out(conductor: Conductor) -> ConductorOut:
    # vehiculo_id sale igual a camion_id (la columna vieja vehiculo_id ya no se expone).
    return ConductorOut.model_validate(conductor).model_copy(
        update={"vehiculo_id": conductor.camion_id}
    )


@router.get("/conductores", response_model=list[ConductorOut])
def listar_conductores(db: Session = Depends(get_db)):
    return [
        _a_conductor_out(c) for c in db.query(Conductor).order_by(Conductor.id).all()
    ]


@router.post(
    "/conductores", response_model=ConductorOut, status_code=status.HTTP_201_CREATED
)
def crear_conductor(datos: ConductorCreate, db: Session = Depends(get_db)):
    _, camion_id = _resolver_camion(db, datos.model_dump(exclude_unset=True))

    campos = datos.model_dump(exclude={"camion_id", "vehiculo_id"})
    conductor = Conductor(**campos, camion_id=camion_id)
    db.add(conductor)
    db.commit()
    db.refresh(conductor)
    return _a_conductor_out(conductor)


@router.patch("/conductores/{conductor_id}", response_model=ConductorOut)
def actualizar_conductor(
    conductor_id: int, datos: ConductorUpdate, db: Session = Depends(get_db)
):
    conductor = db.get(Conductor, conductor_id)
    if conductor is None:
        raise HTTPException(status_code=404, detail="Conductor no encontrado")

    cambios = datos.model_dump(exclude_unset=True)
    enviado, camion_id = _resolver_camion(db, cambios)
    cambios.pop("camion_id", None)
    cambios.pop("vehiculo_id", None)
    if enviado:
        conductor.camion_id = camion_id

    for campo, valor in cambios.items():
        setattr(conductor, campo, valor)
    db.commit()
    db.refresh(conductor)
    return _a_conductor_out(conductor)


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
