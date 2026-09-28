from app.database import Base, engine
from app.models.nodo import Nodo
from app.models.lectura import Lectura

Base.metadata.create_all(bind=engine)
print("Tablas creadas correctamente.")