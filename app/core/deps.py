import secrets

import jwt
from fastapi import Depends, Header, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import DEVICE_API_KEY
from app.core.security import decode_token
from app.database import get_db
from app.models.usuario import Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> Usuario:
    error = HTTPException(
        status_code=401,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise error

    user = db.get(Usuario, user_id)
    if user is None or not user.activo:
        raise error
    return user


def require_roles(*roles: str):
    def checker(user: Usuario = Depends(get_current_user)) -> Usuario:
        if user.rol not in roles:
            raise HTTPException(status_code=403, detail="No tienes permiso para esta acción")
        return user

    return checker


def verify_device_key(x_api_key: str = Header(default="")):
    if not DEVICE_API_KEY or not secrets.compare_digest(
        x_api_key.encode(), DEVICE_API_KEY.encode()
    ):
        raise HTTPException(status_code=401, detail="API key de dispositivo inválida")