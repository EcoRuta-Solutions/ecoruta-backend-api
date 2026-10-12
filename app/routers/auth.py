from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.database import get_db
from app.models.usuario import Usuario
from app.schemas.usuario import RegistroCiudadano, Token, UsuarioOut
from app.core.deps import require_roles

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post("/registro", response_model=UsuarioOut, status_code=201)
def registro(datos: RegistroCiudadano, db: Session = Depends(get_db)):
    # El registro público SOLO crea ciudadanos. El rol no lo elige el cliente.
    email = datos.email.lower()
    if db.query(Usuario).filter(Usuario.email == email).first():
        raise HTTPException(status_code=409, detail="Ese email ya está registrado")

    usuario = Usuario(
        email=email,
        nombre=datos.nombre,
        password_hash=hash_password(datos.password),
        rol="ciudadano",
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


@router.post("/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # El formulario estándar llama "username" al campo; aquí es el email
    usuario = db.query(Usuario).filter(Usuario.email == form.username.lower()).first()

    if usuario is None or not usuario.activo or not verify_password(
        form.password, usuario.password_hash
    ):
        # Mismo mensaje en ambos casos, para no revelar qué emails existen
        raise HTTPException(status_code=401, detail="Email o contraseña incorrectos")

    token = create_access_token(usuario.id, usuario.rol)
    return Token(access_token=token, rol=usuario.rol, nombre=usuario.nombre)


@router.get("/me", response_model=UsuarioOut)
def yo(usuario: Usuario = Depends(get_current_user)):
    return usuario


# REQUERIMIENTO 3: Endpoint para registrar municipalidad / conductor
# Adaptado exactamente al patrón existente, extendiendo RegistroCiudadano para incluir el campo 'rol'
class UsuarioCreate(RegistroCiudadano):
    rol: str


@router.post("/registro-staff", response_model=UsuarioOut, status_code=201,
             dependencies=[Depends(require_roles("municipalidad"))])
def registrar_staff(datos: UsuarioCreate, db: Session = Depends(get_db)):
    # Copiamos el patrón de conversión a minúsculas del endpoint /registro original
    email = datos.email.lower()
    
    existe = db.query(Usuario).filter(Usuario.email == email).first()
    if existe:
        raise HTTPException(status_code=409, detail="Ese email ya está registrado")

    if datos.rol not in ("municipalidad", "conductor"):
        raise HTTPException(status_code=400, detail="Rol inválido para este endpoint")

    # Mapeo de campos idéntico a tu función 'registro' original para resguardar la contraseña
    usuario = Usuario(
        email=email,
        nombre=datos.nombre,
        password_hash=hash_password(datos.password),  # Asegura el patrón de hashing existente
        rol=datos.rol,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario
