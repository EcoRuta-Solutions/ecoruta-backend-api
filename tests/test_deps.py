from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.deps import require_roles


@pytest.mark.parametrize("rol", ["municipalidad", "conductor"])
def test_require_roles_acepta_roles_autorizados(rol):
    usuario = SimpleNamespace(rol=rol)

    assert require_roles("municipalidad", "conductor")(usuario) is usuario


@pytest.mark.parametrize("rol", ["conductor", "rol_inexistente"])
def test_require_roles_rechaza_rol_no_autorizado(rol):
    with pytest.raises(HTTPException) as error:
        require_roles("municipalidad")(SimpleNamespace(rol=rol))

    assert error.value.status_code == 403
