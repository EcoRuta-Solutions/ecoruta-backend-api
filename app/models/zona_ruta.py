from sqlalchemy import Boolean, Column, Integer, String, Text, Time, false

from app.database import Base


class ZonaRuta(Base):
    """Ruta de recolección por zona (M-1, T-3, N-9…) según el horario oficial.

    Se carga con scripts/importar_rutas_zona.py desde data/rutas_zona_trujillo.csv.
    """

    __tablename__ = "zonas_ruta"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String, unique=True, index=True, nullable=False)
    # Valor de app.core.turnos.Turno: "manana", "tarde" o "noche".
    turno = Column(String, nullable=False, index=True)
    tramo = Column(String, nullable=True)
    sectores = Column(Text, nullable=True)
    recojo_inicio = Column(Time, nullable=False)
    recojo_fin = Column(Time, nullable=False)
    # Horario en que los vecinos sacan la basura; vacío si el listado no lo trae.
    sacar_basura_inicio = Column(Time, nullable=True)
    sacar_basura_fin = Column(Time, nullable=True)
    # Calculado por el importador a partir de recojo_inicio/recojo_fin.
    cruza_medianoche = Column(Boolean, nullable=False, default=False, server_default=false())
    # True si el dato es dudoso y hay que confirmarlo con SEGAT.
    revisar = Column(Boolean, nullable=False, default=False, server_default=false())
