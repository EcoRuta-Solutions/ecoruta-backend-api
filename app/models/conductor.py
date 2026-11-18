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
    # Heredado: id de la tabla vieja `vehiculos`. Ya no se escribe desde la API;
    # scripts/vincular_conductores_camion.py lo usa (con SQL) para llenar camion_id
    # por placa. Sin ForeignKey en el ORM: el modelo Vehiculo ya no se carga en la
    # app, y declararla rompía el flush de Conductor (NoReferencedTableError).
    # La FK que pueda existir en la base no se toca.
    vehiculo_id = Column(Integer, nullable=True)
    # Relación vigente.
    camion_id = Column(Integer, ForeignKey("camiones.id"), nullable=True, index=True)
    activo = Column(Boolean, nullable=False, default=True)
    # True para los conductores de seed_demo.py.
    es_demo = Column(Boolean, nullable=False, default=False, server_default=false())
