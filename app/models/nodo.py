from sqlalchemy import Column, Integer, String, Float
from app.database import Base


class Nodo(Base):
    __tablename__ = "nodos"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String, unique=True, index=True, nullable=False)
    nombre = Column(String, nullable=False)
    latitud = Column(Float, nullable=False)
    longitud = Column(Float, nullable=False)
    umbral_critico = Column(Integer, default=80, nullable=False)