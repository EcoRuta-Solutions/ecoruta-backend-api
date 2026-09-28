from app.database import SessionLocal
from app.models.nodo import Nodo
from app.models.lectura import Lectura

db = SessionLocal()

# 1. Buscar si el nodo ya existe (para poder correr el script varias veces)
nodo = db.query(Nodo).filter(Nodo.codigo == "TRU-001").first()

if nodo is None:
    nodo = Nodo(
        codigo="TRU-001",
        nombre="Plaza de Armas",
        latitud=-8.1116,
        longitud=-79.0288,
    )
    db.add(nodo)
    db.commit()
    db.refresh(nodo)  # recarga el objeto para obtener el id que asignó la base

print(f"Nodo guardado: id={nodo.id}, codigo={nodo.codigo}, nombre={nodo.nombre}")

# 2. Guardar una lectura que apunta a ese nodo con su id numérico
lectura = Lectura(nodo_id=nodo.id, fill_pct=63.5, tilt_alert=False)
db.add(lectura)
db.commit()

# 3. Leer las lecturas de ese nodo
lecturas = db.query(Lectura).filter(Lectura.nodo_id == nodo.id).all()
for l in lecturas:
    print(f"Lectura {l.id}: {l.fill_pct}% a las {l.timestamp}")

db.close()