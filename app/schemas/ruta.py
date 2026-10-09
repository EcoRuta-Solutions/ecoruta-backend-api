from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.camion import CamionOut

class ParadaBaseCreate(BaseModel):
    nodo_id: int
    orden: int

class RutaCreate(BaseModel):
    fecha_inicio: date
    fecha_fin: date
    hora_inicio: datetime
    hora_fin: datetime
    camion_id: int
    paradas: List[ParadaBaseCreate] = Field(default_factory=list)

class ParadaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ruta_id: int
    nodo_id: int
    orden: int

class RutaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fecha_inicio: date
    fecha_fin: date
    hora_inicio: datetime
    hora_fin: datetime
    camion_id: int
    estado: str
    camion: Optional[CamionOut] = None
    paradas: List[ParadaOut] = Field(default_factory=list)