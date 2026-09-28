from datetime import datetime
from pydantic import BaseModel


class NodoEstado(BaseModel):
    id: int
    codigo: str
    nombre: str
    latitud: float
    longitud: float
    umbral_critico: int
    fill_pct: float | None
    tilt_alert: bool | None
    ultima_lectura: datetime | None
    estado: str  # "critico", "alerta", "normal" o "sin_datos"


class Resumen(BaseModel):
    total_nodos: int
    criticos: int
    alertas: int
    normales: int
    sin_datos: int
    promedio_llenado: float | None