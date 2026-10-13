from enum import Enum

from sqlalchemy import CheckConstraint, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class EstadoReporte(str, Enum):
    PENDIENTE = "pendiente"
    EN_ATENCION = "en_atencion"
    ATENDIDO = "atendido"


class ReporteCiudadano(Base):
    __tablename__ = "reportes_ciudadanos"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('pendiente', 'en_atencion', 'atendido')",
            name="ck_reportes_ciudadanos_estado",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    latitud = Column(Float, nullable=False)
    longitud = Column(Float, nullable=False)
    foto_url = Column(Text, nullable=True)
    descripcion = Column(String(1000), nullable=False)
    estado = Column(
        String(20), nullable=False, default=EstadoReporte.PENDIENTE.value, index=True
    )
    asignado_a = Column(String(120), nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)