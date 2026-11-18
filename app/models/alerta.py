from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.sql import func

from app.database import Base

TIPO_CONTENEDOR_LLENO = "contenedor_lleno"


class Alerta(Base):
    """Alerta para municipalidad y conductores (p. ej. "Contenedor lleno: PROTO-UTP (92%)").

    Se crea UNA vez cuando el sensor de un punto pasa a lleno/desbordado y se
    resuelve cuando el nivel baja del umbral de lleno o el punto se recolecta.
    """

    __tablename__ = "alertas"

    id = Column(Integer, primary_key=True, index=True)
    tipo = Column(String, nullable=False)
    punto_critico_id = Column(Integer, ForeignKey("puntos_criticos.id"), nullable=False, index=True)
    mensaje = Column(String, nullable=False)
    # Nivel del sensor cuando se creó la alerta.
    nivel_pct = Column(Float, nullable=True)
    activa = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    creada_en = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resuelta_en = Column(DateTime(timezone=True), nullable=True)
    # "nivel_bajo" | "recolectado"
    motivo_resolucion = Column(String, nullable=True)

    __table_args__ = (
        # Como máximo una alerta ACTIVA por punto y tipo (evita duplicados aun con
        # lecturas simultáneas).
        Index(
            "uq_alertas_activa_por_punto",
            "punto_critico_id",
            "tipo",
            unique=True,
            postgresql_where=text("activa"),
        ),
    )
