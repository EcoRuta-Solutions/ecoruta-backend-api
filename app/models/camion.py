from sqlalchemy import Column, Integer, String
from app.database import Base

class Camion(Base):
    __tablename__ = "camiones"

    id = Column(Integer, primary_key=True, index=True)
    placa = Column(String(7), unique=True, index=True, nullable=False) # 7 caracteres porque las placas tienen 3 letras y 3 números, separados por un guion
    capacidad = Column(Integer, nullable=False)
    turno = Column(String, nullable=False) # Mañana, Tarde, Noche