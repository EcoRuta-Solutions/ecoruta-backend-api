from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class LecturaCreate(BaseModel):
    codigo: str
    fill_pct: float = Field(ge=0, le=100)
    tilt_alert: bool = False


class LecturaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nodo_id: int
    fill_pct: float
    tilt_alert: bool
    timestamp: datetime