from app.database import Base, engine

from app.models.nodo import Nodo
from app.models.lectura import Lectura
from app.models.usuario import Usuario
from app.models.camion import Camion
from app.models.ruta import Ruta, Parada
from app.models.vehiculo import Vehiculo
from app.models.conductor import Conductor

Base.metadata.create_all(bind=engine)

print(
    "Tablas registradas:",
    sorted(Base.metadata.tables.keys()),
)
