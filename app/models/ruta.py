from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    false,
)
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
    conductor_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    estado = Column(String, nullable=False) # Pendiente, en_proceso, Completado, Cancelado
    # True para las rutas de seed_demo.py (y las de camiones demo).
    es_demo = Column(Boolean, nullable=False, default=False, server_default=false())
    # Datos del generador por turno (POST /rutas/generar); null en rutas creadas a mano.
    turno = Column(String, nullable=True)  # valor de app.core.turnos.Turno
    distancia_km = Column(Float, nullable=True)
    tiempo_estimado_min = Column(Float, nullable=True)
    metodo_distancia = Column(String, nullable=True)  # osrm | haversine_aprox

    camion = relationship("Camion")
    conductor = relationship("Usuario")
    paradas = relationship("Parada", back_populates="ruta", cascade="all, delete-orphan")

class Parada(Base):
    __tablename__ = "paradas"

    id = Column(Integer, primary_key=True, index=True)
    ruta_id = Column(Integer, ForeignKey("rutas.id"), nullable=False)
    # Una parada es un nodo (contenedor con sensor) o un punto crítico oficial.
    nodo_id = Column(Integer, ForeignKey("nodos.id"), nullable=True)
    punto_critico_id = Column(
        Integer, ForeignKey("puntos_criticos.id"), nullable=True, index=True
    )
    orden = Column(Integer, nullable=False) # Orden de la parada en la ruta
    recolectado = Column(Boolean, nullable=False, default=False)

    ruta = relationship("Ruta", back_populates="paradas")
    nodo = relationship("Nodo")
    punto_critico = relationship("PuntoCritico")

    __table_args__ = (
        CheckConstraint(
            "nodo_id IS NOT NULL OR punto_critico_id IS NOT NULL",
            name="ck_paradas_nodo_o_punto",
        ),
    )
