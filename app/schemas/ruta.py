from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.turnos import Turno, normalizar_turno

from app.schemas.camion import CamionOut
from app.schemas.nodo import NodoOut


class ParadaBaseCreate(BaseModel):
    nodo_id: int = Field(gt=0)
    orden: int = Field(ge=1)


class RutaCreate(BaseModel):
    fecha_inicio: date
    fecha_fin: date
    hora_inicio: datetime
    hora_fin: datetime
    camion_id: int = Field(gt=0)
    conductor_id: int | None = Field(default=None, gt=0)
    paradas: list[ParadaBaseCreate] = Field(
        default_factory=list
    )


class RutaEstadoUpdate(BaseModel):
    estado: Literal["Pendiente", "en_proceso", "Completado", "Cancelado"]


class ParadaUpdate(BaseModel):
    recolectado: bool


class NodoParadaOut(NodoOut):
    """Nodo con su última lectura, para mostrarlo dentro de una ruta.

    `llenado` es el último fill_pct conocido y `prioridad` una etiqueta
    legible derivada del estado (Crítica, Alta o Media). Ambos son None
    cuando el nodo todavía no tiene lecturas.
    """

    llenado: float | None = None
    prioridad: str | None = None


class PuntoParadaOut(BaseModel):
    """Punto crítico visitado por una parada, con su estado de llenado vigente."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str = Field(validation_alias="codigo_unico")
    direccion: str
    referencia: str | None = None
    lat: float
    lon: float
    priorizacion_obligatoria: bool
    # Del último reporte de campo vigente; "sin_datos" si no hay (nunca supuesto).
    estado_llenado: str = "sin_datos"


class ParadaOut(BaseModel):
    id: int
    ruta_id: int
    # Una parada es un nodo (sensor) o un punto crítico: uno de los dos es null.
    nodo_id: int | None = None
    punto_critico_id: int | None = None
    orden: int
    recolectado: bool = False
    nodo: NodoParadaOut | None = None
    punto_critico: PuntoParadaOut | None = None

    model_config = ConfigDict(from_attributes=True)


class RutaOut(BaseModel):
    id: int
    fecha_inicio: date
    fecha_fin: date
    hora_inicio: datetime
    hora_fin: datetime
    camion_id: int
    conductor_id: int | None = None
    estado: str
    turno: str | None = Field(default=None, description="Solo en rutas generadas por turno")
    distancia_km: float | None = None
    tiempo_estimado_min: float | None = None
    metodo_distancia: str | None = Field(default=None, description="osrm | haversine_aprox")
    camion: CamionOut | None = None
    paradas: list[ParadaOut] = Field(
        default_factory=list
    )

    model_config = ConfigDict(from_attributes=True)


class RutaGenerarRequest(BaseModel):
    turno: Turno
    fecha: date | None = Field(default=None, description="Por defecto, hoy")
    solo_prioritarios: bool = Field(default=False, description="Solo puntos de priorización obligatoria")
    solo_con_reporte_lleno: bool = Field(
        default=False, description="Solo puntos con reporte vigente lleno o desbordado"
    )
    incluir_reserva: bool = Field(default=False, description="Usar también los camiones en reserva")
    max_paradas_por_ruta: int | None = Field(
        default=None, ge=1, description="Por defecto ceil(puntos / camiones)"
    )

    @field_validator("turno", mode="before")
    @classmethod
    def _turno(cls, valor):
        turno = normalizar_turno(valor) if isinstance(valor, str) else valor
        if turno is None:
            raise ValueError("turno debe ser manana, tarde o noche")
        return turno


class ParadaGeneradaOut(BaseModel):
    orden: int
    punto_critico_id: int
    codigo: str
    lat: float
    lon: float
    direccion: str


class CamionRutaOut(BaseModel):
    id: int
    placa: str


class RutaGeneradaOut(BaseModel):
    ruta_id: int
    camion: CamionRutaOut
    conductor_id: int | None
    hora_inicio: datetime
    hora_fin: datetime
    excede_turno: bool = Field(description="True si la hora estimada de fin pasa el fin del turno")
    distancia_km: float
    tiempo_estimado_min: float
    paradas: list[ParadaGeneradaOut]


class ParametrosGeneracionOut(BaseModel):
    velocidad_media_kmh: float
    minutos_por_parada: float
    factor_circuito: float | None = Field(description="Solo con metodo_distancia=haversine_aprox")
    capacidad_camion_usada: bool
    provisionales: list[str]
    notas: list[str]


class RutasTurnoOut(BaseModel):
    turno: Turno
    fecha: date
    nro_camiones: int
    nro_puntos: int
    max_paradas_por_ruta: int
    metodo_distancia: str = Field(description="osrm | haversine_aprox")
    distancia_total_km: float
    tiempo_total_min: float
    rutas_reemplazadas: int
    camiones_con_ruta_en_curso: list[str]
    parametros: ParametrosGeneracionOut
    rutas: list[RutaGeneradaOut]


class RutaMiaOut(BaseModel):
    """Respuesta de POST /rutas/generar-mia (una ruta para el camión del conductor)."""

    nro_puntos: int
    metodo_distancia: str = Field(description="osrm | osrm_parcial | haversine_aprox")
    rutas_reemplazadas: int
    parametros: ParametrosGeneracionOut
    ruta: RutaGeneradaOut
