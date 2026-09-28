from sqlalchemy import Column, Integer, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class Lectura(Base):
    __tablename__ = "lecturas"

    id = Column(Integer, primary_key=True, index=True)
    nodo_id = Column(Integer, ForeignKey("nodos.id"), nullable=False, index=True)
    fill_pct = Column(Float, nullable=False)
    tilt_alert = Column(Boolean, default=False, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)