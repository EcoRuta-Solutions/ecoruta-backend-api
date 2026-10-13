from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from app.database import Base


class Conductor(Base):
    __tablename__ = "conductores"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True, index=True)
    nombre = Column(String, nullable=False)
    telefono = Column(String, nullable=False, default="")
    categoria_licencia = Column(String, nullable=False, default="A-IIb")
    estado = Column(String, nullable=False, default="disponible")  # disponible, en_ruta, descanso
    vehiculo_id = Column(Integer, ForeignKey("vehiculos.id"), nullable=True)
    activo = Column(Boolean, nullable=False, default=True)
