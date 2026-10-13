from sqlalchemy import Boolean, Column, Float, Integer, String
from app.database import Base


class Vehiculo(Base):
    __tablename__ = "vehiculos"

    id = Column(Integer, primary_key=True, index=True)
    placa = Column(String(7), unique=True, index=True, nullable=False)
    tipo = Column(String, nullable=False, default="Compactador")
    capacidad_toneladas = Column(Float, nullable=False, default=8)
    estado = Column(String, nullable=False, default="operativo")  # operativo, mantenimiento
    activo = Column(Boolean, nullable=False, default=True)
