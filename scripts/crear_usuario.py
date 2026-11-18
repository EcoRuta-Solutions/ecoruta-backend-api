r"""Crea una cuenta REAL (es_demo = false, activo = true) o cambia su contraseña.

No hay registro público ni endpoint para crear usuarios: las cuentas reales se
crean con este script, en la máquina que tiene acceso a la base.

La contraseña:
- se pide con getpass (no se ve al escribirla), dos veces para confirmarla;
- debe tener al menos 8 caracteres (y como máximo 72 bytes, límite de bcrypt);
- NO se acepta por argumento ni por variable de entorno, y nunca se imprime ni
  se registra: solo se guarda su hash, con la misma función que usa el login
  (app.core.security.hash_password).

El correo se guarda en minúsculas (el login lo busca así).

Uso:
    .\venv\Scripts\python.exe scripts\crear_usuario.py --nombre "Ana Pérez" --correo ana.perez@ejemplo.pe --rol conductor
    .\venv\Scripts\python.exe scripts\crear_usuario.py --correo ana.perez@ejemplo.pe --actualizar-clave

Si el correo ya existe, no se modifica nada (salvo con --actualizar-clave, que
solo cambia la contraseña de esa cuenta).
"""

import argparse
import getpass
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func

from app.core.security import hash_password
from app.models.usuario import Usuario

ROLES = ("municipalidad", "conductor")
MINIMO_CARACTERES = 8
MAXIMO_BYTES = 72  # bcrypt no acepta contraseñas más largas


class ErrorUsuario(ValueError):
    """Dato inválido o situación que impide continuar (mensaje para el usuario)."""


def normalizar_correo(correo: str) -> str:
    try:
        valido = validate_email((correo or "").strip(), check_deliverability=False)
    except EmailNotValidError as error:
        raise ErrorUsuario(f"Correo inválido: {error}")
    return valido.normalized.lower()


def validar_rol(rol: str | None) -> str:
    rol = (rol or "").strip().lower()
    if rol not in ROLES:
        raise ErrorUsuario(f"Rol inválido: debe ser {' o '.join(ROLES)}")
    return rol


def validar_nombre(nombre: str | None) -> str:
    nombre = " ".join((nombre or "").split())
    if not nombre:
        raise ErrorUsuario("Falta --nombre")
    return nombre


def validar_clave(clave: str) -> None:
    if len(clave) < MINIMO_CARACTERES:
        raise ErrorUsuario(f"La contraseña debe tener al menos {MINIMO_CARACTERES} caracteres")
    if len(clave.encode()) > MAXIMO_BYTES:
        raise ErrorUsuario(f"La contraseña no puede pasar de {MAXIMO_BYTES} bytes")
    if not clave.strip():
        raise ErrorUsuario("La contraseña no puede ser solo espacios")


def pedir_clave() -> str:
    """Pide la contraseña dos veces sin mostrarla. No la imprime nunca."""
    clave = getpass.getpass("Contraseña: ")
    validar_clave(clave)
    if getpass.getpass("Repite la contraseña: ") != clave:
        raise ErrorUsuario("Las contraseñas no coinciden. No se guardó nada.")
    return clave


def buscar(db, correo: str) -> Usuario | None:
    return db.query(Usuario).filter(func.lower(Usuario.email) == correo).first()


def resumen(usuario: Usuario) -> str:
    return (
        f"id: {usuario.id}\nnombre: {usuario.nombre}\n"
        f"correo: {usuario.email}\nrol: {usuario.rol}"
    )


def ejecutar(db, args) -> tuple[str, Usuario]:
    """Crea la cuenta o cambia su contraseña. Devuelve (accion, usuario)."""
    correo = normalizar_correo(args.correo)
    existente = buscar(db, correo)

    if args.actualizar_clave:
        if existente is None:
            raise ErrorUsuario(f"No existe una cuenta con el correo {correo}. No se creó nada.")
        clave = pedir_clave()
        existente.password_hash = hash_password(clave)
        db.commit()
        return "clave_actualizada", existente

    if existente is not None:
        raise ErrorUsuario(
            f"Ya existe una cuenta con el correo {correo} (id {existente.id}); no se modificó. "
            "Usa --actualizar-clave para cambiar su contraseña."
        )

    nombre = validar_nombre(args.nombre)
    rol = validar_rol(args.rol)
    clave = pedir_clave()  # se pide al final, cuando todo lo demás es válido
    usuario = Usuario(
        email=correo,
        nombre=nombre,
        password_hash=hash_password(clave),
        rol=rol,
        activo=True,
        es_demo=False,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return "creado", usuario


def parsear(argv: list[str] | None):
    parser = argparse.ArgumentParser(
        description="Crea una cuenta real o cambia su contraseña (la contraseña se pide por teclado)."
    )
    parser.add_argument("--correo", required=True)
    parser.add_argument("--nombre", help="Obligatorio al crear")
    parser.add_argument("--rol", help=f"Obligatorio al crear: {' | '.join(ROLES)}")
    parser.add_argument(
        "--actualizar-clave",
        action="store_true",
        help="Solo cambia la contraseña de una cuenta que ya existe",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, sesion=None) -> None:
    args = parsear(argv)
    if sesion is None:
        from app.database import SessionLocal

        sesion = SessionLocal

    with sesion() as db:
        try:
            accion, usuario = ejecutar(db, args)
        except ErrorUsuario as error:
            db.rollback()
            raise SystemExit(f"ERROR: {error}")
        except (KeyboardInterrupt, EOFError):
            db.rollback()
            raise SystemExit("\nCancelado. No se guardó nada.")

        titulo = "Usuario creado:" if accion == "creado" else "Contraseña actualizada para:"
        print(titulo)
        print(resumen(usuario))


if __name__ == "__main__":
    main()
