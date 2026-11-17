from sqlalchemy import Column, Integer, String, Boolean, false
from app.database import Base


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    nombre = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    rol = Column(String, nullable=False)
    activo = Column(Boolean, nullable=False, default=True)
    # True para las cuentas de scripts/crear_usuarios_demo.py.
    es_demo = Column(Boolean, nullable=False, default=False, server_default=false())
