from pydantic import BaseModel, ConfigDict, Field


class VehiculoBase(BaseModel):
    placa: str = Field(min_length=7, max_length=7)
    tipo: str = Field(default="Compactador")
    capacidad_toneladas: float = Field(default=8, gt=0)
    estado: str = Field(default="operativo")
    activo: bool = True


class VehiculoCreate(VehiculoBase):
    pass


class VehiculoUpdate(BaseModel):
    placa: str | None = Field(default=None, min_length=7, max_length=7)
    tipo: str | None = None
    capacidad_toneladas: float | None = Field(default=None, gt=0)
    estado: str | None = None
    activo: bool | None = None


class VehiculoOut(VehiculoBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


class ConductorBase(BaseModel):
    nombre: str = Field(min_length=1)
    telefono: str = ""
    categoria_licencia: str = "A-IIb"
    estado: str = "disponible"
    vehiculo_id: int | None = None
    activo: bool = True


class ConductorCreate(ConductorBase):
    usuario_id: int | None = None


class ConductorUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1)
    telefono: str | None = None
    categoria_licencia: str | None = None
    estado: str | None = None
    vehiculo_id: int | None = None
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
