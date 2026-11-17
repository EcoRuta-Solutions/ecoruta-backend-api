from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.punto_critico import EstadoPuntoCritico
from app.schemas.reporte_campo import EstadoLlenado, UltimoReporteBreve


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
    # Del último reporte de campo (no demo); null si nunca se reportó.
    ultimo_reporte: UltimoReporteBreve | None = None
    # True si el último reporte tiene menos de REPORTE_VIGENCIA_HORAS.
    reporte_vigente: bool = False
    # Estado del último reporte vigente, o "sin_datos": nunca un valor supuesto.
    estado_llenado: EstadoLlenado = "sin_datos"


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
