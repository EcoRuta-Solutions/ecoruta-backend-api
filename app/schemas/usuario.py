from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegistroCiudadano(BaseModel):
    email: EmailStr
    nombre: str
    password: str = Field(min_length=6, max_length=72)


class UsuarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    nombre: str
    rol: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    rol: str
    nombre: str