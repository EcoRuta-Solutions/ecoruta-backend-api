import enum

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, Column, DateTime, Enum, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class EstadoPuntoCritico(str, enum.Enum):
    potencial = "potencial"
    recuperado = "recuperado"


class PuntoCritico(Base):
    """Punto crítico oficial de acumulación de residuos (no es contenedor ni tiene sensor)."""

    __tablename__ = "puntos_criticos"

    id = Column(Integer, primary_key=True, index=True)
    codigo_unico = Column(String, unique=True, index=True, nullable=False)
    estado = Column(
        Enum(
            EstadoPuntoCritico,
            name="estado_punto_critico",
            values_callable=lambda enum_: [m.value for m in enum_],
        ),
        nullable=False,
    )
    priorizacion_obligatoria = Column(Boolean, nullable=False)
    direccion = Column(String, nullable=False)
    referencia = Column(String, nullable=True)
    # Coordenadas UTM zona 17S tal como vienen en el listado oficial.
    este_utm17s = Column(Integer, nullable=True)
    norte_utm17s = Column(Integer, nullable=True)
    # spatial_index=True hace que create_all cree el índice GiST.
    ubicacion = Column(
        Geometry("POINT", srid=4326, spatial_index=True), nullable=False
    )
    creado_en = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
