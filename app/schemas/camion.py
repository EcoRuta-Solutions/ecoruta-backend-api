from pydantic import BaseModel, ConfigDict, Field

from app.core.turnos import Turno
from app.models.camion import EstadoCamion


class CamionBase(BaseModel):
    placa: str = Field(..., max_length=7, min_length=7, description="Placa del camión (3 letras y 3 números, separados por un guion)")
    capacidad: int = Field(..., gt=0, description="Capacidad del camión en kilogramos")
    turno: str = Field(..., description="Turno del camión (Mañana, Tarde, Noche)")

class CamionCreate(CamionBase):
    pass

class CamionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    placa: str
    capacidad: int | None = Field(
        default=None, description="Capacidad en kilogramos; null si no está confirmada"
    )
    turno: str
    capacidad_toneladas: float | None = None
    estado: EstadoCamion = EstadoCamion.operativo
    datos_confirmados: bool = False
    es_demo: bool = False


class CambioEstadoCamion(BaseModel):
    estado: EstadoCamion = Field(description="Nuevo estado del camión")
    activar_reserva: bool = Field(
        default=False,
        description=(
            "Si es true, una reserva del mismo turno pasa a operativo en lugar "
            "de este camión. Solo válido si el camión está operativo y deja de estarlo."
        ),
    )


class CambioEstadoCamionOut(BaseModel):
    camion: CamionOut
    reserva_activada: CamionOut | None = None


class ConteoEstados(BaseModel):
    operativo: int = 0
    reserva: int = 0
    mantenimiento: int = 0
    total: int = 0


class ResumenFlotaOut(BaseModel):
    total: int
    por_estado: ConteoEstados
    por_turno: dict[Turno, ConteoEstados]
    sin_turno_reconocido: int = Field(
        description="Camiones cuyo turno no es mañana, tarde ni noche"
    )
    demo: int = Field(description="Camiones de seed_demo.py incluidos en el total")
    datos_provisionales: int = Field(
        description="Camiones con datos_confirmados=false incluidos en el total"
    )
