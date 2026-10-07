from pydantic import BaseModel


class RutaOptimizadaOut(BaseModel):
    inicio_id: int
    ruta: list[int]
    cantidad_nodos: int
