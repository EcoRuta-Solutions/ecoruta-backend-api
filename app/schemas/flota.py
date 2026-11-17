from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.turnos import normalizar_turno
from app.models.camion import EstadoCamion


def _validar_turno(valor: str | None) -> str | None:
    """Acepta manana/mañana/tarde/noche y guarda el valor de Turno; None = por confirmar."""
    if valor is None:
        return None
    turno = normalizar_turno(valor)
    if turno is None:
        raise ValueError("turno debe ser manana, tarde o noche")
    return turno.value


# /flota/vehiculos (obsoleto): mismo esquema de siempre, pero sobre la tabla `camiones`.
class VehiculoBase(BaseModel):
    placa: str = Field(min_length=7, max_length=7)
    tipo: str | None = Field(default=None, description="null = por confirmar")
    capacidad_toneladas: float | None = Field(
        default=None, gt=0, description="null = por confirmar con SEGAT"
    )
    estado: EstadoCamion = EstadoCamion.operativo
    activo: bool = True


class VehiculoCreate(VehiculoBase):
    turno: str | None = Field(
        default=None, description="manana, tarde o noche; null = por confirmar"
    )

    _turno = field_validator("turno")(_validar_turno)


class VehiculoUpdate(BaseModel):
    placa: str | None = Field(default=None, min_length=7, max_length=7)
    tipo: str | None = None
    capacidad_toneladas: float | None = Field(default=None, gt=0)
    estado: EstadoCamion | None = None
    activo: bool | None = None
    turno: str | None = None

    _turno = field_validator("turno")(_validar_turno)


class VehiculoOut(VehiculoBase):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Id del camión (tabla camiones)")
    estado: str
    turno: str | None = None


class ConductorBase(BaseModel):
    nombre: str = Field(min_length=1)
    telefono: str = ""
    categoria_licencia: str = "A-IIb"
    estado: str = "disponible"
    camion_id: int | None = None
    vehiculo_id: int | None = Field(
        default=None,
        description="Obsoleto: alias de camion_id (id que devuelve /flota/vehiculos)",
    )
    activo: bool = True


class ConductorCreate(ConductorBase):
    usuario_id: int | None = None


class ConductorUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1)
    telefono: str | None = None
    categoria_licencia: str | None = None
    estado: str | None = None
    camion_id: int | None = None
    vehiculo_id: int | None = Field(default=None, description="Obsoleto: alias de camion_id")
    activo: bool | None = None


class ConductorOut(ConductorBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    usuario_id: int | None = None


class UsuarioPanelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    correo: str
    rol: str
    activo: bool


class UsuarioPanelUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1)
    rol: str | None = None
    activo: bool | None = None
