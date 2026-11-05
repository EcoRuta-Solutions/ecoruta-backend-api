import enum

from sqlalchemy import Boolean, Column, Float, Integer, String, false, text

from app.database import Base


class EstadoCamion(str, enum.Enum):
    operativo = "operativo"
    reserva = "reserva"
    mantenimiento = "mantenimiento"


class Camion(Base):
    __tablename__ = "camiones"

    id = Column(Integer, primary_key=True, index=True)
    placa = Column(String(7), unique=True, index=True, nullable=False) # 7 caracteres porque las placas tienen 3 letras y 3 números, separados por un guion
    # Capacidad en kg. Nullable: la capacidad real de la flota aún no está confirmada.
    capacidad = Column(Integer, nullable=True)
    # Capacidad en toneladas; cuando se informa, `capacidad` (kg) = toneladas * 1000.
    capacidad_toneladas = Column(Float, nullable=True)
    # Texto libre por compatibilidad: los camiones demo usan "Mañana"/"Tarde"/"Noche"
    # y los nuevos "manana"/"tarde"/"noche" (ver app.core.turnos.normalizar_turno).
    turno = Column(String, nullable=False)
    estado = Column(
        String,
        nullable=False,
        default=EstadoCamion.operativo.value,
        server_default=text(f"'{EstadoCamion.operativo.value}'"),
    )
    # False mientras placa/capacidad sean provisionales.
    datos_confirmados = Column(Boolean, nullable=False, default=False, server_default=false())
    # True para los camiones que crea seed_demo.py.
    es_demo = Column(Boolean, nullable=False, default=False, server_default=false())
