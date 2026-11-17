from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, false
from app.database import Base


class Conductor(Base):
    __tablename__ = "conductores"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True, index=True)
    nombre = Column(String, nullable=False)
    telefono = Column(String, nullable=False, default="")
    categoria_licencia = Column(String, nullable=False, default="A-IIb")
    estado = Column(String, nullable=False, default="disponible")  # disponible, en_ruta, descanso
    # Heredado: apunta a la tabla vieja `vehiculos`. Ya no se escribe desde la API;
    # scripts/vincular_conductores_camion.py lo usa para llenar camion_id por placa.
    vehiculo_id = Column(Integer, ForeignKey("vehiculos.id"), nullable=True)
    camion_id = Column(Integer, ForeignKey("camiones.id"), nullable=True, index=True)
    activo = Column(Boolean, nullable=False, default=True)
    # True para los conductores de seed_demo.py.
    es_demo = Column(Boolean, nullable=False, default=False, server_default=false())
