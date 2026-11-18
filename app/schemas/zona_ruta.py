from datetime import time

from pydantic import BaseModel, ConfigDict

from app.core.turnos import Turno


class ZonaRutaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    turno: Turno
    tramo: int
    sectores: str | None
    recojo_inicio: time
    recojo_fin: time
    sacar_basura_inicio: time | None
    sacar_basura_fin: time | None
    cruza_medianoche: bool
    revisar: bool
