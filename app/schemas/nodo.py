from pydantic import BaseModel, ConfigDict


class NodoCreate(BaseModel):
    codigo: str
    nombre: str
    latitud: float
    longitud: float
    umbral_critico: int = 80


class NodoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    nombre: str
    latitud: float
    longitud: float
    umbral_critico: int