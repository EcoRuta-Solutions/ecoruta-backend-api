from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LecturaSensorIn(BaseModel):
    codigo: str = Field(min_length=1, description="Código del nodo/sensor, p. ej. PROTO-UTP")
    nivel_pct: float = Field(ge=0, le=120, description="Nivel de llenado medido (%), 0–120")


class AlertaBreve(BaseModel):
    id: int
    mensaje: str


class LecturaSensorOut(BaseModel):
    lectura_id: int
    codigo: str
    nivel_pct: float
    estado_llenado: Literal["vacio", "medio", "lleno", "desbordado"]
    punto_codigo: str | None = Field(description="Punto crítico vinculado al sensor, si hay")
    vigente_hasta: datetime | None = Field(
        description="Hasta cuándo vale este dato como estado del punto (luego: sin_datos)"
    )
    alerta_creada: AlertaBreve | None = Field(
        description="Alerta nueva si esta lectura pasó el contenedor a lleno/desbordado"
    )
    alertas_resueltas: int
