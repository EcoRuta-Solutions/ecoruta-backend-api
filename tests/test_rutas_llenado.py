from types import SimpleNamespace

from app.routers import rutas
from app.routers.rutas import _enriquecer_llenado


def test_enriquecer_llenado_adjunta_llenado_y_prioridad(monkeypatch):
    estados = [
        SimpleNamespace(id=1, fill_pct=92.0, estado="critico"),
        SimpleNamespace(id=2, fill_pct=55.0, estado="alerta"),
        SimpleNamespace(id=3, fill_pct=10.0, estado="normal"),
    ]
    monkeypatch.setattr(rutas, "obtener_estados", lambda db: estados)

    nodo1 = SimpleNamespace(id=1)
    nodo2 = SimpleNamespace(id=2)
    nodo3 = SimpleNamespace(id=3)
    nodo_sin_lecturas = SimpleNamespace(id=99)
    ruta = SimpleNamespace(
        paradas=[
            SimpleNamespace(nodo=nodo1),
            SimpleNamespace(nodo=nodo2),
            SimpleNamespace(nodo=nodo3),
            SimpleNamespace(nodo=nodo_sin_lecturas),
            SimpleNamespace(nodo=None),
        ]
    )

    _enriquecer_llenado(object(), [ruta])

    assert (nodo1.llenado, nodo1.prioridad) == (92.0, "Crítica")
    assert (nodo2.llenado, nodo2.prioridad) == (55.0, "Alta")
    assert (nodo3.llenado, nodo3.prioridad) == (10.0, "Media")
    assert nodo_sin_lecturas.llenado is None
    assert nodo_sin_lecturas.prioridad is None
