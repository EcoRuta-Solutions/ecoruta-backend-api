from app.database import Base, engine
from app.models.nodo import Nodo
from app.models.lectura import Lectura
from app.models.usuario import Usuario

Base.metadata.create_all(bind=engine)

print("Tablas registradas:", sorted(Base.metadata.tables.keys()))