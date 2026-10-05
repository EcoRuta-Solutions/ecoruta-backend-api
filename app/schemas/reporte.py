from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.models.reporte import EstadoReporte


class ReporteCrear(BaseModel):
    latitud: float = Field(ge=-90, le=90)
    longitud: float = Field(ge=-180, le=180)
    descripcion: str = Field(min_length=1, max_length=1000)
    foto_url: HttpUrl | None = None


class ReporteActualizar(BaseModel):
    estado: Literal["atendido"] = "atendido"


class ReporteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    usuario_id: int
    latitud: float
    longitud: float
    foto_url: str | None
    descripcion: str
    estado: EstadoReporte
    timestamp: datetime