from datetime import date

from pydantic import BaseModel


class KpiInforme(BaseModel):
    clave: str
    nombre: str
    valor: float
    meta: float
    unidad: str
    mayor_es_mejor: bool


class PuntoSerieInforme(BaseModel):
    fecha: date
    valor: float


class InformeResumen(BaseModel):
    inicio: date
    fin: date
    kpis: list[KpiInforme]
    llenado_promedio: list[PuntoSerieInforme]
    desbordes_por_zona: dict[str, int]
    kilometros_optimizados: list[PuntoSerieInforme]
    kilometros_fijos: list[PuntoSerieInforme]
