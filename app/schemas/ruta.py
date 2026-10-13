from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.camion import CamionOut
from app.schemas.nodo import NodoOut


class ParadaBaseCreate(BaseModel):
    nodo_id: int = Field(gt=0)
    orden: int = Field(ge=1)


class RutaCreate(BaseModel):
    fecha_inicio: date
    fecha_fin: date
    hora_inicio: datetime
    hora_fin: datetime
    camion_id: int = Field(gt=0)
    conductor_id: int | None = Field(default=None, gt=0)
    paradas: list[ParadaBaseCreate] = Field(
        default_factory=list
    )


class RutaEstadoUpdate(BaseModel):
    estado: Literal["Pendiente", "en_proceso", "Completado", "Cancelado"]


class ParadaUpdate(BaseModel):
    recolectado: bool


class NodoParadaOut(NodoOut):
    """Nodo con su última lectura, para mostrarlo dentro de una ruta.

    `llenado` es el último fill_pct conocido y `prioridad` una etiqueta
    legible derivada del estado (Crítica, Alta o Media). Ambos son None
    cuando el nodo todavía no tiene lecturas.
    """

    llenado: float | None = None
    prioridad: str | None = None


class ParadaOut(BaseModel):
    id: int
    ruta_id: int
    nodo_id: int
    orden: int
    recolectado: bool = False
    nodo: NodoParadaOut | None = None

    model_config = ConfigDict(from_attributes=True)


class RutaOut(BaseModel):
    id: int
    fecha_inicio: date
    fecha_fin: date
    hora_inicio: datetime
    hora_fin: datetime
    camion_id: int
    conductor_id: int | None = None
    estado: str
    camion: CamionOut | None = None
    paradas: list[ParadaOut] = Field(
        default_factory=list
    )

    model_config = ConfigDict(from_attributes=True)


class RutaGenerarRequest(BaseModel):
    fecha: date
    camion_id: int = Field(gt=0)
    conductor_id: int | None = Field(default=None, gt=0)
    inicio_id: int | None = Field(default=None, gt=0)


class RutaGenerarOut(BaseModel):
    ruta: RutaOut
    metodo: str
    distancia_km: float
    distancia_ortools_km: float
    distancia_heuristica_km: float
