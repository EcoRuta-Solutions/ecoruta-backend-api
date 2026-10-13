"""Crea (o restablece) los usuarios demo con una contraseña conocida.

`POST /auth/registro` solo crea ciudadanos, así que para probar el panel
municipal y la app del conductor hacen falta usuarios con otros roles. Este
script los deja listos sin cambiar los ids de las cuentas existentes (las rutas
sembradas apuntan al conductor existente).

Uso:
    python scripts/crear_usuarios_demo.py

Credenciales resultantes (contraseña: demo1234):
    user@example.com            ciudadano
    conductor@ecoruta.com       conductor
    municipalidad3@ecoruta.com  municipalidad
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security import hash_password
from app.database import SessionLocal
from app.models.usuario import Usuario

PASSWORD = "demo1234"

CUENTAS = [
    ("user@example.com", "Ciudadano Demo", "ciudadano"),
    ("conductor@ecoruta.com", "Conductor Demo", "conductor"),
    ("municipalidad3@ecoruta.com", "Municipalidad Demo", "municipalidad"),
]


def main() -> None:
    db = SessionLocal()
    try:
        for email, nombre, rol in CUENTAS:
            usuario = db.query(Usuario).filter(Usuario.email == email).first()
            if usuario is None:
                usuario = Usuario(
                    email=email,
                    nombre=nombre,
                    password_hash=hash_password(PASSWORD),
                    rol=rol,
                    activo=True,
                )
                db.add(usuario)
                print(f"Creado: {email} ({rol})")
            else:
                usuario.password_hash = hash_password(PASSWORD)
                usuario.rol = rol
                usuario.activo = True
                print(f"Actualizado: {email} ({rol}, id {usuario.id})")
        db.commit()
    finally:
        db.close()

    print(f"\nContraseña para todos: {PASSWORD}")


if __name__ == "__main__":
    main()
