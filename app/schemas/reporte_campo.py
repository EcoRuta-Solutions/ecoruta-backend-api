from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.reporte_campo import EstadoReporte

# Estado que muestra un punto: el del último reporte vigente o "sin_datos".
EstadoLlenado = Literal["vacio", "medio", "lleno", "desbordado", "sin_datos"]


class ReporteCampoCreate(BaseModel):
    codigo_punto: str = Field(min_length=1, description="Código del punto crítico, p. ej. 130101-1")
    estado: EstadoReporte
    observacion: str | None = Field(default=None, max_length=1000)
    lat: float | None = Field(default=None, ge=-90, le=90, description="Latitud del dispositivo")
    lon: float | None = Field(default=None, ge=-180, le=180, description="Longitud del dispositivo")

    @model_validator(mode="after")
    def _lat_lon_juntos(self):
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat y lon deben enviarse juntos")
        return self


class ReporteCampoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    punto_critico_id: int
    codigo_punto: str
    usuario_id: int | None = Field(description="null si el reporte viene de un sensor")
    usuario_nombre: str | None
    origen: Literal["campo", "sensor"] = "campo"
    nivel_pct: float | None = Field(default=None, description="Solo en reportes de sensor")
    estado: EstadoReporte
    observacion: str | None
    lat: float | None
    lon: float | None
    distancia_m: float | None = Field(description="null si el reporte no trajo GPS")
    lejos_del_punto: bool
    foto_url: str | None
    creado_en: datetime
    es_demo: bool


class ReportesCampoPagina(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ReporteCampoOut]


class UltimoReporteBreve(BaseModel):
    estado: EstadoReporte
    creado_en: datetime
    origen: Literal["campo", "sensor"] = "campo"
    nivel_pct: float | None = None


class UltimoReportePuntoOut(BaseModel):
    codigo: str
    reporte_vigente: bool
    estado_llenado: EstadoLlenado
    vigencia_horas: float
    reporte: ReporteCampoOut | None = Field(description="null si el punto nunca fue reportado")


class ConteoPorEstadoLlenado(BaseModel):
    vacio: int
    medio: int
    lleno: int
    desbordado: int


class ResumenReportesOut(BaseModel):
    total_puntos: int
    vigencia_horas: float
    por_estado: ConteoPorEstadoLlenado
    sin_datos: int = Field(description="Puntos sin reporte vigente (sin reporte o vencido)")
