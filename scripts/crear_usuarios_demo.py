r"""Crea (o restablece) las cuentas DEMO, con una contraseña que NO está en el código.

No hay registro público: para probar el panel municipal y la app del conductor
hacen falta usuarios con esos roles. Este script deja listas las cuentas demo
(es_demo = true) sin cambiar los ids de las cuentas existentes.

Las cuentas REALES se crean con scripts/crear_usuario.py, no con este script.

La contraseña de las cuentas demo:
- se toma de la variable de entorno ECORUTA_DEMO_PASSWORD si está definida
  (útil en una máquina de pruebas), o si no
- se pide por consola con getpass, dos veces para confirmarla.
Debe tener al menos 8 caracteres. Nunca se imprime ni se guarda en el repo.

Uso:
    .\venv\Scripts\python.exe scripts\crear_usuarios_demo.py

Cuentas (rol):
    conductor@ecoruta.com       conductor
    municipalidad3@ecoruta.com  municipalidad
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from crear_usuario import ErrorUsuario, pedir_clave, validar_clave
from migrar_es_demo import migrar

from app.core.security import hash_password
from app.models.usuario import Usuario

VARIABLE_CLAVE = "ECORUTA_DEMO_PASSWORD"

CUENTAS = [
    ("conductor@ecoruta.com", "Conductor Demo", "conductor"),
    ("municipalidad3@ecoruta.com", "Municipalidad Demo", "municipalidad"),
]


def obtener_clave() -> str:
    """Contraseña demo desde ECORUTA_DEMO_PASSWORD o, si no está, pedida por consola."""
    clave = os.environ.get(VARIABLE_CLAVE)
    if clave is not None:
        validar_clave(clave)
        return clave
    return pedir_clave()


def main(sesion=None, engine=None) -> None:
    if sesion is None or engine is None:
        from app.database import SessionLocal
        from app.database import engine as engine_app

        sesion = sesion or SessionLocal
        engine = engine or engine_app

    try:
        clave = obtener_clave()
    except ErrorUsuario as error:
        raise SystemExit(f"ERROR: {error}")
    except (KeyboardInterrupt, EOFError):
        raise SystemExit("\nCancelado. No se guardó nada.")

    migrar(engine)  # columna usuarios.es_demo
    password_hash = hash_password(clave)
    with sesion() as db:
        for email, nombre, rol in CUENTAS:
            usuario = db.query(Usuario).filter(Usuario.email == email).first()
            if usuario is None:
                db.add(
                    Usuario(
                        email=email,
                        nombre=nombre,
                        password_hash=password_hash,
                        rol=rol,
                        activo=True,
                        es_demo=True,
                    )
                )
                print(f"Creado: {email} ({rol})")
            else:
                usuario.password_hash = password_hash
                usuario.rol = rol
                usuario.activo = True
                usuario.es_demo = True
                print(f"Actualizado: {email} ({rol}, id {usuario.id})")
        db.commit()

    print("\nContraseña de las cuentas demo: la que ingresaste (no se muestra).")


if __name__ == "__main__":
    main()
