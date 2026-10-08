from pydantic import BaseModel, Field

class CamionBase(BaseModel):
    placa: str = Field(..., max_length=7, min_length=7, description="Placa del camión (3 letras y 3 números, separados por un guion)")
    capacidad: int = Field(..., gt=0, description="Capacidad del camión en kilogramos")
    turno: str = Field(..., description="Turno del camión (Mañana, Tarde, Noche)")

class CamionCreate(CamionBase):
    pass

class CamionOut(CamionBase):
    id: int

    class Config:
        from_attributes = True