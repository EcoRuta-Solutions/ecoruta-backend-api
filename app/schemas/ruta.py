from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.camion import CamionOut


class ParadaBaseCreate(BaseModel):
    nodo_id: int = Field(gt=0)
    orden: int = Field(ge=1)


class RutaCreate(BaseModel):
    fecha_inicio: date
    fecha_fin: date
    hora_inicio: datetime
    hora_fin: datetime
    camion_id: int = Field(gt=0)
    paradas: list[ParadaBaseCreate] = Field(
        default_factory=list
    )


class ParadaOut(BaseModel):
    id: int
    ruta_id: int
    nodo_id: int
    orden: int

    model_config = ConfigDict(from_attributes=True)


class RutaOut(BaseModel):
    id: int
    fecha_inicio: date
    fecha_fin: date
    hora_inicio: datetime
    hora_fin: datetime
    camion_id: int
    estado: str
    camion: CamionOut | None = None
    paradas: list[ParadaOut] = Field(
        default_factory=list
    )

    model_config = ConfigDict(from_attributes=True)


class RutaGenerarRequest(BaseModel):
    fecha: date
    camion_id: int = Field(gt=0)
    inicio_id: int | None = Field(default=None, gt=0)


class RutaGenerarOut(BaseModel):
    ruta: RutaOut
    metodo: str
    distancia_km: float
    distancia_ortools_km: float
    distancia_heuristica_km: float
