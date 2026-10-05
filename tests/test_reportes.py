from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.deps import require_roles
from app.schemas.reporte import ReporteActualizar, ReporteCrear
from app.schemas.usuario import UsuarioOut


def test_reporte_crear_acepta_limites_geograficos_y_foto_opcional():
    reporte = ReporteCrear(
        latitud=-90,
        longitud=180,
        descripcion="Punto crítico",
    )

    assert reporte.foto_url is None


@pytest.mark.parametrize(
    ("field", "value"),
    [("latitud", 90.1), ("latitud", -90.1), ("longitud", 180.1), ("longitud", -180.1)],
)
def test_reporte_crear_rechaza_coordenadas_fuera_de_rango(field, value):
    datos = {
        "latitud": 0,
        "longitud": 0,
        "descripcion": "Punto crítico",
        field: value,
    }

    with pytest.raises(ValidationError):
        ReporteCrear.model_validate(datos)


def test_reporte_crear_rechaza_descripcion_demasiado_larga():
    with pytest.raises(ValidationError):
        ReporteCrear(latitud=0, longitud=0, descripcion="x" * 1001)


def test_reporte_actualizar_solo_permite_atendido():
    assert ReporteActualizar().estado == "atendido"
    with pytest.raises(ValidationError):
        ReporteActualizar(estado="pendiente")


def test_usuario_out_devuelve_emails_de_usuarios_de_prueba():
    usuario = UsuarioOut(id=1, email="ciudadano@ecoruta.test", nombre="Ciudadano", rol="ciudadano")

    assert usuario.email == "ciudadano@ecoruta.test"


@pytest.mark.parametrize("rol", ["municipalidad", "conductor"])
def test_require_roles_acepta_roles_autorizados(rol):
    usuario = SimpleNamespace(rol=rol)

    assert require_roles("municipalidad", "conductor")(usuario) is usuario


def test_require_roles_rechaza_rol_no_autorizado():
    with pytest.raises(HTTPException) as error:
        require_roles("municipalidad")(SimpleNamespace(rol="ciudadano"))

    assert error.value.status_code == 403