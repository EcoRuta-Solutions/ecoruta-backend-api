from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PrediccionOut(BaseModel):
    nodo_id: int
    codigo: str
    fill_pct_actual: float | None
    umbral_critico: float
    horas_estimadas: float | None
    fecha_estimada_critico: datetime | None
    metodo: Literal["modelo", "lineal"]
    confianza: float = Field(ge=0, le=1)
    calculado_en: datetime