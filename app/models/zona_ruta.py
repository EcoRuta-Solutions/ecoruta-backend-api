from sqlalchemy import Boolean, Column, Integer, String, Text, Time, UniqueConstraint, false

from app.database import Base


class ZonaRuta(Base):
    """Un TRAMO de una ruta de recolección por zona (M-1, N-9…) del horario oficial.

    Cada ruta tiene uno o más tramos (1, 2, 3…) con sus sectores y horarios; una
    fila por tramo. Se carga con scripts/importar_rutas_zona.py desde
    data/rutas_zona_trujillo.csv.
    """

    __tablename__ = "zonas_ruta"

    id = Column(Integer, primary_key=True, index=True)
    # Código de la ruta; se repite en cada tramo. Único junto con `tramo`.
    codigo = Column(String, index=True, nullable=False)
    # Valor de app.core.turnos.Turno: "manana", "tarde" o "noche".
    turno = Column(String, nullable=False, index=True)
    # Número de tramo dentro de la ruta (1, 2, 3…).
    tramo = Column(Integer, nullable=False)
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

    __table_args__ = (
        UniqueConstraint("codigo", "tramo", name="uq_zonas_ruta_codigo_tramo"),
    )
