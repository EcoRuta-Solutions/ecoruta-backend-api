import enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    false,
)
from sqlalchemy.sql import func

from app.database import Base


class EstadoReporte(str, enum.Enum):
    vacio = "vacio"
    medio = "medio"
    lleno = "lleno"
    desbordado = "desbordado"


class ReporteCampo(Base):
    """Nivel de llenado de un punto crítico observado en campo por un usuario.

    Es la única fuente de ese dato: no hay sensores en los puntos críticos ni
    datos públicos. Nunca se generan reportes simulados.
    """

    __tablename__ = "reportes_campo"

    id = Column(Integer, primary_key=True, index=True)
    punto_critico_id = Column(
        Integer, ForeignKey("puntos_criticos.id"), nullable=False, index=True
    )
    # Sale del JWT de quien reporta, nunca del payload.
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    estado = Column(
        Enum(
            EstadoReporte,
            name="estado_reporte_campo",
            values_callable=lambda enum_: [m.value for m in enum_],
        ),
        nullable=False,
    )
    observacion = Column(Text, nullable=True)
    # Posición del dispositivo al reportar (WGS84); opcional.
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    # Distancia en metros entre el dispositivo y el punto; null si no hubo GPS.
    distancia_m = Column(Float, nullable=True)
    # True si distancia_m supera REPORTE_DISTANCIA_MAX_M. El reporte se guarda igual.
    lejos_del_punto = Column(Boolean, nullable=False, default=False, server_default=false())
    # Reservado para adjuntar una foto más adelante.
    foto_url = Column(Text, nullable=True)
    creado_en = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Hereda es_demo del usuario que reporta; los demo no cuentan como estado real.
    es_demo = Column(Boolean, nullable=False, default=False, server_default=false())

    __table_args__ = (
        # Último reporte por punto (DISTINCT ON punto ORDER BY creado_en DESC).
        Index("ix_reportes_campo_punto_creado", "punto_critico_id", creado_en.desc()),
    )
