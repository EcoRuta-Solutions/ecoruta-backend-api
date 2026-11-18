from datetime import datetime

from pydantic import BaseModel


class AlertaOut(BaseModel):
    id: int
    tipo: str
    mensaje: str
    nivel_pct: float | None
    punto_critico_id: int
    punto_codigo: str
    direccion: str
    lat: float
    lon: float
    creada_en: datetime
