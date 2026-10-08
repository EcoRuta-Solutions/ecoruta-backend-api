from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base

class Ruta(Base):
    __tablename__ = "rutas"

    id = Column(Integer, primary_key=True, index=True)
    fecha_inicio = Column(Date, nullable=False)
    fecha_fin = Column(Date, nullable=False)
    hora_inicio = Column(DateTime, nullable=False)
    hora_fin = Column(DateTime, nullable=False)
    camion_id = Column(Integer, ForeignKey("camiones.id"), nullable=False)
    estado = Column(String, nullable=False) # Pendiente, en_proceso, Completado, Cancelado

    camion = relationship("Camion")
    paradas = relationship("Parada", back_populates="ruta", cascade="all, delete-orphan")

class Parada(Base):
    __tablename__ = "paradas"

    id = Column(Integer, primary_key=True, index=True)
    ruta_id = Column(Integer, ForeignKey("rutas.id"), nullable=False)
    nodo_id = Column(Integer, ForeignKey("nodos.id"), nullable=False)
    orden = Column(Integer, nullable=False) # Orden de la parada en la ruta

    ruta = relationship("Ruta", back_populates="paradas")
    nodo = relationship("Nodo")