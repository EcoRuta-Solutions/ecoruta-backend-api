"""Reportes de campo: captura, distancia al punto, filtros, vigencia y resumen.

Los reportes de estas pruebas se crean a mano para ejercitar la lógica; no son
datos reales ni simulan lecturas.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import config
from app.core.security import create_access_token
from app.database import get_db
from app.main import app
from app.models.punto_critico import PuntoCritico
from app.models.reporte_campo import ReporteCampo
from app.models.usuario import Usuario
from conftest import importador

# 130101-1 está en lat -8.084408, lon -79.045583 (CSV de prueba de conftest).
LAT_1, LON_1 = -8.084408, -79.045583
# ~0.0009° de latitud ≈ 100 m; ~0.0018° ≈ 200 m.
CERCA = (LAT_1 + 0.0009, LON_1)
LEJOS = (LAT_1 + 0.0018, LON_1)


@pytest.fixture
def entorno(db_limpia, csv_prueba):
    importador.importar(db_limpia, csv_prueba)
    Sesion = sessionmaker(bind=db_limpia, autoflush=False)
    tokens, ids = {}, {}
    with Sesion() as db:
        cuentas = [
            ("municipalidad", "municipalidad", False),
            ("conductor", "conductor", False),
            ("invitado", "invitado", False),
            ("demo", "conductor", True),
        ]
        for nombre, rol, demo in cuentas:
            usuario = Usuario(
                email=f"{nombre}@prueba.test", nombre=nombre.title(),
                password_hash="x", rol=rol, es_demo=demo,
            )
            db.add(usuario)
            db.flush()
            tokens[nombre] = create_access_token(usuario.id, rol)
            ids[nombre] = usuario.id
        db.commit()

    def get_db_pruebas():
        db = Sesion()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = get_db_pruebas
    try:
        yield TestClient(app), tokens, ids, Sesion
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def cliente(entorno):
    cliente, tokens, _, _ = entorno
    cliente.headers["Authorization"] = f"Bearer {tokens['conductor']}"
    return cliente


def agregar(Sesion, codigo, estado, horas_atras, usuario_id, es_demo=False):
    """Inserta un reporte con fecha controlada (para probar orden y vigencia)."""
    with Sesion() as db:
        punto_id = db.scalar(select(PuntoCritico.id).where(PuntoCritico.codigo_unico == codigo))
        reporte = ReporteCampo(
            punto_critico_id=punto_id,
            usuario_id=usuario_id,
            estado=estado,
            creado_en=datetime.now(timezone.utc) - timedelta(hours=horas_atras),
            es_demo=es_demo,
        )
        db.add(reporte)
        db.commit()
        return reporte.id


def reportar(cliente, **cuerpo):
    return cliente.post("/reportes-campo", json={"codigo_punto": "130101-1", "estado": "lleno", **cuerpo})


# --- Crear --------------------------------------------------------------------------


@pytest.mark.parametrize("rol", ["municipalidad", "conductor"])
def test_roles_autorizados_pueden_reportar(entorno, rol):
    cliente, tokens, ids, _ = entorno

    respuesta = cliente.post(
        "/reportes-campo",
        json={"codigo_punto": "130101-1", "estado": "medio"},
        headers={"Authorization": f"Bearer {tokens[rol]}"},
    )

    assert respuesta.status_code == 201
    reporte = respuesta.json()
    assert reporte["usuario_id"] == ids[rol]
    assert reporte["codigo_punto"] == "130101-1"
    assert reporte["estado"] == "medio"
    assert reporte["foto_url"] is None


def test_rol_no_autorizado_y_sin_token(entorno):
    cliente, tokens, _, _ = entorno
    cuerpo = {"codigo_punto": "130101-1", "estado": "lleno"}

    assert cliente.post("/reportes-campo", json=cuerpo).status_code == 401
    assert cliente.post(
        "/reportes-campo", json=cuerpo, headers={"Authorization": f"Bearer {tokens['invitado']}"}
    ).status_code == 403


def test_usuario_sale_del_jwt_no_del_payload(entorno, cliente):
    _, _, ids, _ = entorno

    respuesta = reportar(cliente, usuario_id=ids["municipalidad"])

    assert respuesta.status_code == 201
    assert respuesta.json()["usuario_id"] == ids["conductor"]
    assert respuesta.json()["usuario_nombre"] == "Conductor"


@pytest.mark.parametrize(
    ("cambios", "codigo"),
    [
        ({"estado": "medio_lleno"}, 422),
        ({"estado": ""}, 422),
        ({"codigo_punto": "130101-999"}, 404),
        ({"lat": LAT_1}, 422),  # lat sin lon
        ({"lat": 95, "lon": LON_1}, 422),
        ({"observacion": "x" * 1001}, 422),
    ],
)
def test_crear_rechaza(cliente, cambios, codigo):
    assert reportar(cliente, **cambios).status_code == codigo


def test_observacion_y_sin_gps(cliente):
    reporte = reportar(cliente, observacion="  Bolsas en la vereda  ").json()

    assert reporte["observacion"] == "Bolsas en la vereda"
    assert (reporte["lat"], reporte["lon"], reporte["distancia_m"]) == (None, None, None)
    assert reporte["lejos_del_punto"] is False


# --- Distancia al punto -----------------------------------------------------------


def test_en_el_punto_distancia_cero(cliente):
    reporte = reportar(cliente, lat=LAT_1, lon=LON_1).json()

    assert reporte["distancia_m"] == pytest.approx(0, abs=0.5)
    assert reporte["lejos_del_punto"] is False


def test_a_100_m_no_esta_lejos(cliente):
    reporte = reportar(cliente, lat=CERCA[0], lon=CERCA[1]).json()

    assert reporte["distancia_m"] == pytest.approx(99.5, abs=2)
    assert reporte["lejos_del_punto"] is False


def test_a_200_m_esta_lejos_pero_se_guarda(entorno, cliente):
    _, _, _, Sesion = entorno

    respuesta = reportar(cliente, lat=LEJOS[0], lon=LEJOS[1])

    assert respuesta.status_code == 201
    assert respuesta.json()["distancia_m"] == pytest.approx(199, abs=3)
    assert respuesta.json()["lejos_del_punto"] is True
    with Sesion() as db:
        assert db.query(ReporteCampo).count() == 1


def test_umbral_de_distancia_es_configurable(cliente, monkeypatch):
    monkeypatch.setattr(config, "REPORTE_DISTANCIA_MAX_M", 50)

    assert reportar(cliente, lat=CERCA[0], lon=CERCA[1]).json()["lejos_del_punto"] is True


# --- Listado y filtros ---------------------------------------------------------------


def test_listado_ordenado_y_paginado(entorno, cliente):
    _, _, ids, Sesion = entorno
    viejo = agregar(Sesion, "130101-1", "vacio", 30, ids["conductor"])
    medio = agregar(Sesion, "130101-2", "medio", 5, ids["conductor"])
    nuevo = agregar(Sesion, "130101-1", "lleno", 1, ids["municipalidad"])

    cuerpo = cliente.get("/reportes-campo").json()
    assert cuerpo["total"] == 3
    assert [r["id"] for r in cuerpo["items"]] == [nuevo, medio, viejo]

    pagina = cliente.get("/reportes-campo", params={"limit": 1, "offset": 1}).json()
    assert (pagina["total"], pagina["limit"], pagina["offset"]) == (3, 1, 1)
    assert [r["id"] for r in pagina["items"]] == [medio]


def test_filtros_por_punto_y_fechas(entorno, cliente):
    _, _, ids, Sesion = entorno
    viejo = agregar(Sesion, "130101-1", "vacio", 30, ids["conductor"])
    agregar(Sesion, "130101-2", "medio", 5, ids["conductor"])
    nuevo = agregar(Sesion, "130101-1", "lleno", 1, ids["conductor"])
    ahora = datetime.now(timezone.utc)

    def ids_de(**params):
        return [r["id"] for r in cliente.get("/reportes-campo", params=params).json()["items"]]

    assert ids_de(punto="130101-1") == [nuevo, viejo]
    assert ids_de(punto="130101-4") == []
    assert ids_de(punto="130101-1", desde=(ahora - timedelta(hours=10)).isoformat()) == [nuevo]
    assert ids_de(hasta=(ahora - timedelta(hours=10)).isoformat()) == [viejo]


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"desde": "ayer"},
     {"desde": "2026-11-02T00:00:00Z", "hasta": "2026-11-01T00:00:00Z"}],
)
def test_listado_rechaza_parametros_invalidos(cliente, params):
    assert cliente.get("/reportes-campo", params=params).status_code == 422


def test_reportes_de_cuenta_demo_quedan_aparte(entorno):
    cliente, tokens, _, _ = entorno
    demo = cliente.post(
        "/reportes-campo",
        json={"codigo_punto": "130101-1", "estado": "desbordado"},
        headers={"Authorization": f"Bearer {tokens['demo']}"},
    ).json()
    cabecera = {"Authorization": f"Bearer {tokens['conductor']}"}

    assert demo["es_demo"] is True
    assert cliente.get("/reportes-campo", headers=cabecera).json()["total"] == 0
    con_demo = cliente.get("/reportes-campo", params={"incluir_demo": "true"}, headers=cabecera)
    assert con_demo.json()["total"] == 1
    # No cuenta como estado real del punto.
    ultimo = cliente.get("/puntos-criticos/130101-1/ultimo-reporte", headers=cabecera).json()
    assert ultimo["estado_llenado"] == "sin_datos"
    assert cliente.get("/reportes-campo/resumen", headers=cabecera).json()["sin_datos"] == 4


# --- Vigencia y último reporte --------------------------------------------------------


def test_ultimo_reporte_vigente(entorno, cliente):
    _, _, ids, Sesion = entorno
    agregar(Sesion, "130101-1", "vacio", 10, ids["conductor"])
    agregar(Sesion, "130101-1", "lleno", 23, ids["conductor"])
    reciente = agregar(Sesion, "130101-1", "desbordado", 2, ids["municipalidad"])

    cuerpo = cliente.get("/puntos-criticos/130101-1/ultimo-reporte").json()

    assert cuerpo["codigo"] == "130101-1"
    assert cuerpo["reporte_vigente"] is True
    assert cuerpo["estado_llenado"] == "desbordado"
    assert cuerpo["vigencia_horas"] == 24
    assert cuerpo["reporte"]["id"] == reciente


def test_reporte_de_mas_de_24_h_queda_sin_datos(entorno, cliente):
    _, _, ids, Sesion = entorno
    agregar(Sesion, "130101-1", "lleno", 25, ids["conductor"])

    cuerpo = cliente.get("/puntos-criticos/130101-1/ultimo-reporte").json()
    punto = cliente.get("/puntos-criticos/130101-1").json()

    assert cuerpo["reporte_vigente"] is False
    assert cuerpo["estado_llenado"] == "sin_datos"
    assert cuerpo["reporte"]["estado"] == "lleno"  # se muestra, pero no vale como estado
    assert punto["reporte_vigente"] is False
    assert punto["estado_llenado"] == "sin_datos"
    assert punto["ultimo_reporte"]["estado"] == "lleno"


def test_vigencia_es_configurable(entorno, cliente, monkeypatch):
    _, _, ids, Sesion = entorno
    agregar(Sesion, "130101-1", "medio", 2, ids["conductor"])
    monkeypatch.setattr(config, "REPORTE_VIGENCIA_HORAS", 1)

    cuerpo = cliente.get("/puntos-criticos/130101-1/ultimo-reporte").json()

    assert (cuerpo["reporte_vigente"], cuerpo["estado_llenado"], cuerpo["vigencia_horas"]) == (
        False, "sin_datos", 1,
    )


def test_punto_sin_reportes(cliente):
    cuerpo = cliente.get("/puntos-criticos/130101-2/ultimo-reporte")

    assert cuerpo.status_code == 200
    assert cuerpo.json() == {
        "codigo": "130101-2",
        "reporte_vigente": False,
        "estado_llenado": "sin_datos",
        "vigencia_horas": 24,
        "reporte": None,
    }


def test_ultimo_reporte_de_punto_inexistente_404(cliente):
    respuesta = cliente.get("/puntos-criticos/130101-999/ultimo-reporte")

    assert respuesta.status_code == 404
    assert respuesta.json()["detail"] == "Punto crítico no encontrado"


def test_listado_de_puntos_incluye_ultimo_reporte(entorno, cliente):
    _, _, ids, Sesion = entorno
    agregar(Sesion, "130101-1", "medio", 3, ids["conductor"])
    agregar(Sesion, "130101-2", "lleno", 48, ids["conductor"])

    puntos = {p["codigo"]: p for p in cliente.get("/puntos-criticos").json()["items"]}

    assert puntos["130101-1"]["estado_llenado"] == "medio"
    assert puntos["130101-1"]["reporte_vigente"] is True
    assert puntos["130101-1"]["ultimo_reporte"]["estado"] == "medio"
    assert puntos["130101-2"]["estado_llenado"] == "sin_datos"
    assert puntos["130101-2"]["ultimo_reporte"]["estado"] == "lleno"
    for codigo in ("130101-3", "130101-4"):
        assert puntos[codigo]["ultimo_reporte"] is None
        assert puntos[codigo]["reporte_vigente"] is False
        assert puntos[codigo]["estado_llenado"] == "sin_datos"


# --- Resumen ---------------------------------------------------------------------------


def test_resumen_sin_ningun_reporte(cliente):
    assert cliente.get("/reportes-campo/resumen").json() == {
        "total_puntos": 4,
        "vigencia_horas": 24,
        "por_estado": {"vacio": 0, "medio": 0, "lleno": 0, "desbordado": 0},
        "sin_datos": 4,
    }


def test_resumen_cuenta_solo_el_ultimo_reporte_vigente(entorno, cliente):
    _, _, ids, Sesion = entorno
    agregar(Sesion, "130101-1", "vacio", 5, ids["conductor"])
    agregar(Sesion, "130101-1", "desbordado", 1, ids["conductor"])  # el último manda
    agregar(Sesion, "130101-2", "lleno", 2, ids["conductor"])
    agregar(Sesion, "130101-3", "medio", 30, ids["conductor"])  # vencido
    # 130101-4 nunca reportado

    resumen = cliente.get("/reportes-campo/resumen").json()

    assert resumen["total_puntos"] == 4
    assert resumen["por_estado"] == {"vacio": 0, "medio": 0, "lleno": 1, "desbordado": 1}
    assert resumen["sin_datos"] == 2


def test_resumen_roles(entorno):
    cliente, tokens, _, _ = entorno

    assert cliente.get("/reportes-campo/resumen").status_code == 401
    assert cliente.get(
        "/reportes-campo/resumen", headers={"Authorization": f"Bearer {tokens['invitado']}"}
    ).status_code == 403
    assert cliente.get(
        "/reportes-campo/resumen", headers={"Authorization": f"Bearer {tokens['municipalidad']}"}
    ).status_code == 200
