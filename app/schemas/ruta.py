from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel
from app.schemas.camion import CamionOut

class ParadaBaseCreate(BaseModel):
    nodo_id: int
    orden: int
    hora_estimada: Optional[datetime] = None

class ParadaOut(BaseModel):
    id: int
    ruta_id: int
    nodo_id: int
    orden: int
    hora_estimada: Optional[datetime] = None
    camion: CamionOut

    class Config:
        from_attributes = True

class RutaOut(BaseModel):
    id: int
    fecha: date
    camion_id: int
    estado: str
    camion: Optional[CamionOut] = None
    paradas: List[ParadaOut] = []

    class Config:
        from_attributes = True