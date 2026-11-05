from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.punto_critico import EstadoPuntoCritico


class PuntoCriticoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    estado: EstadoPuntoCritico
    priorizacion_obligatoria: bool
    direccion: str
    referencia: str | None
    lat: float
    lon: float
    este_utm17s: int | None
    norte_utm17s: int | None
    creado_en: datetime


class PuntosCriticosPagina(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PuntoCriticoOut]


class ConteoPorEstado(BaseModel):
    potencial: int
    recuperado: int


class ConteoPorPrioridad(BaseModel):
    prioritarios: int
    no_prioritarios: int


class ResumenPuntosCriticos(BaseModel):
    total: int
    por_estado: ConteoPorEstado
    por_prioridad: ConteoPorPrioridad
