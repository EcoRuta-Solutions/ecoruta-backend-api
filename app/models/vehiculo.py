from sqlalchemy import Boolean, Column, Float, Integer, String, false
from app.database import Base


class Vehiculo(Base):
    """Tabla heredada. La flota vive en `camiones`; /flota/vehiculos ya lee de ahí."""

    __tablename__ = "vehiculos"

    id = Column(Integer, primary_key=True, index=True)
    placa = Column(String(7), unique=True, index=True, nullable=False)
    tipo = Column(String, nullable=False, default="Compactador")
    # Sin default: la capacidad real está por confirmar con SEGAT (null = por confirmar).
    capacidad_toneladas = Column(Float, nullable=True)
    estado = Column(String, nullable=False, default="operativo")  # operativo, mantenimiento
    activo = Column(Boolean, nullable=False, default=True)
    # True para los vehículos de seed_demo.py.
    es_demo = Column(Boolean, nullable=False, default=False, server_default=false())
