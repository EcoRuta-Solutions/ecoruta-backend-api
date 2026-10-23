from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers import flota
from app.schemas.flota import UsuarioPanelUpdate


class FakeDB:
    def __init__(self, usuario=None):
        self.usuario = usuario
        self.commits = 0

    def get(self, modelo, id):
        return self.usuario

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        pass


def usuario(rol, nombre="Usuario de prueba", activo=True):
    return SimpleNamespace(
        id=7, nombre=nombre, email="usuario@example.com", rol=rol, activo=activo
    )


@pytest.mark.parametrize(
    ("rol_actual", "rol_panel"),
    [("conductor", "operador"), ("municipalidad", "administrador")],
)
@pytest.mark.parametrize("rol_enviado", ["administrador", "operador", "supervisor"])
def test_actualizar_usuario_no_modifica_el_rol(rol_actual, rol_panel, rol_enviado):
    u = usuario(rol_actual)
    db = FakeDB(u)

    salida = flota.actualizar_usuario_panel(
        7, UsuarioPanelUpdate(nombre="Nombre nuevo", rol=rol_enviado), db
    )

    assert u.rol == rol_actual
    assert salida.rol == rol_panel
    assert db.commits == 1


def test_actualizar_usuario_aplica_nombre_y_activo():
    u = usuario("conductor", nombre="Nombre anterior", activo=True)

    salida = flota.actualizar_usuario_panel(
        7, UsuarioPanelUpdate(nombre="Nombre nuevo", activo=False), FakeDB(u)
    )

    assert u.nombre == "Nombre nuevo"
    assert u.activo is False
    assert salida.nombre == "Nombre nuevo"
    assert salida.activo is False
    assert salida.correo == "usuario@example.com"


def test_actualizar_usuario_inexistente_devuelve_404():
    db = FakeDB(None)

    with pytest.raises(HTTPException) as error:
        flota.actualizar_usuario_panel(99, UsuarioPanelUpdate(nombre="X"), db)

    assert error.value.status_code == 404
    assert db.commits == 0
