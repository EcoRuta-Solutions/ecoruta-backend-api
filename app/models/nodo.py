from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from app.database import Base

class Nodo(Base):
    __tablename__ = "nodos"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String, unique=True, index=True)
    nombre = Column(String)
    latitud = Column(Float)
    longitud = Column(Float)
    umbral_critico = Column(Integer, default=80)

    # Campos que el frontend ya espera y faltaban:
    zona = Column(String, nullable=True)
    capacidad_litros = Column(Integer, nullable=True)
    bateria = Column(Integer, nullable=True)
    senal = Column(Integer, nullable=True)
    estado_operativo = Column(String, nullable=True, default="activo")
    firmware = Column(String, nullable=True)
    tipo_residuo = Column(String, nullable=True)
    fecha_instalacion = Column(DateTime(timezone=True), nullable=True)