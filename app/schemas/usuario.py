from pydantic import BaseModel, ConfigDict


class UsuarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    nombre: str
    rol: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    rol: str
    nombre: str