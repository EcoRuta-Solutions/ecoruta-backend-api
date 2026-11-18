"""scripts/crear_usuario.py: cuentas reales con la contraseña pedida por getpass (simulado)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.security import hash_password, verify_password
from app.database import get_db
from app.main import app
from app.models.usuario import Usuario
from conftest import _cargar_script

m = _cargar_script("crear_usuario")

CLAVE = "Clave-de-prueba-123"  # solo para estas pruebas


@pytest.fixture
def sesion(db_limpia):
    return sessionmaker(bind=db_limpia, autoflush=False)


@pytest.fixture
def teclear(monkeypatch):
    """Simula lo que la persona escribe en cada getpass, en orden."""

    def configurar(*respuestas):
        pedidos = []  # prompts mostrados desde esta configuración
        cola = list(respuestas)

        def falso(prompt=""):
            pedidos.append(prompt)
            return cola.pop(0)

        monkeypatch.setattr(m.getpass, "getpass", falso)
        return pedidos

    return configurar


def crear(sesion, *extra, correo="ana.perez@ejemplo.pe", nombre="Ana Pérez", rol="conductor"):
    argv = ["--correo", correo]
    if nombre is not None:
        argv += ["--nombre", nombre]
    if rol is not None:
        argv += ["--rol", rol]
    m.main([*argv, *extra], sesion=sesion)


def usuarios(sesion):
    with sesion() as db:
        return db.query(Usuario).order_by(Usuario.id).all()


# --- Crear --------------------------------------------------------------------------------


def test_crea_usuario_real_con_hash(sesion, teclear, capsys):
    pedidos = teclear(CLAVE, CLAVE)

    crear(sesion, correo="  Ana.Perez@Ejemplo.PE ")

    assert pedidos == ["Contraseña: ", "Repite la contraseña: "]
    [usuario] = usuarios(sesion)
    assert (usuario.email, usuario.nombre, usuario.rol) == ("ana.perez@ejemplo.pe", "Ana Pérez", "conductor")
    assert (usuario.activo, usuario.es_demo) == (True, False)
    assert usuario.password_hash != CLAVE
    assert usuario.password_hash.startswith("$2")  # bcrypt, la misma función del login
    assert verify_password(CLAVE, usuario.password_hash)
    salida = capsys.readouterr().out
    assert salida.splitlines() == [
        "Usuario creado:",
        f"id: {usuario.id}",
        "nombre: Ana Pérez",
        "correo: ana.perez@ejemplo.pe",
        "rol: conductor",
    ]


def test_la_cuenta_creada_puede_iniciar_sesion(sesion, teclear):
    teclear(CLAVE, CLAVE)
    crear(sesion, correo="Ana.Perez@Ejemplo.PE", rol="municipalidad")

    def get_db_pruebas():
        with sesion() as db:
            yield db

    app.dependency_overrides[get_db] = get_db_pruebas
    try:
        respuesta = TestClient(app).post(
            "/auth/login", data={"username": "ana.perez@ejemplo.pe", "password": CLAVE}
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert respuesta.status_code == 200
    assert "access_token" in respuesta.json()


def test_la_clave_nunca_aparece_en_la_salida(sesion, teclear, capsys):
    teclear(CLAVE, CLAVE)
    crear(sesion)
    teclear(CLAVE, CLAVE)
    with pytest.raises(SystemExit):
        crear(sesion)  # correo repetido
    teclear(CLAVE, CLAVE + "x")
    with pytest.raises(SystemExit) as error:
        crear(sesion, correo="otra@ejemplo.pe")

    salida = capsys.readouterr()
    assert CLAVE not in salida.out + salida.err + str(error.value)


# --- Correo repetido y --actualizar-clave ------------------------------------------------


def test_correo_repetido_no_se_toca_y_no_pide_clave(sesion, teclear):
    teclear(CLAVE, CLAVE)
    crear(sesion)
    [antes] = usuarios(sesion)

    pedidos = teclear()
    with pytest.raises(SystemExit, match="Ya existe una cuenta.*no se modificó"):
        crear(sesion, correo="ANA.PEREZ@ejemplo.pe", nombre="Otro Nombre", rol="municipalidad")

    assert pedidos == []  # avisa antes de pedir la contraseña
    [despues] = usuarios(sesion)
    assert (despues.nombre, despues.rol, despues.password_hash) == (antes.nombre, antes.rol, antes.password_hash)


def test_actualizar_clave_solo_cambia_la_contrasena(sesion, teclear, capsys):
    teclear(CLAVE, CLAVE)
    crear(sesion)
    nueva = "Otra-clave-segura-456"
    teclear(nueva, nueva)

    m.main(["--correo", "ana.perez@ejemplo.pe", "--actualizar-clave"], sesion=sesion)

    [usuario] = usuarios(sesion)
    assert verify_password(nueva, usuario.password_hash)
    assert not verify_password(CLAVE, usuario.password_hash)
    assert (usuario.nombre, usuario.rol, usuario.es_demo) == ("Ana Pérez", "conductor", False)
    salida = capsys.readouterr().out
    assert "Contraseña actualizada para:" in salida
    assert nueva not in salida


def test_actualizar_clave_no_cambia_el_es_demo_de_una_cuenta_demo(sesion, teclear):
    with sesion() as db:
        db.add(Usuario(email="conductor@ecoruta.com", nombre="Demo", password_hash=hash_password("x" * 8),
                       rol="conductor", es_demo=True))
        db.commit()
    teclear(CLAVE, CLAVE)

    m.main(["--correo", "conductor@ecoruta.com", "--actualizar-clave"], sesion=sesion)

    [usuario] = usuarios(sesion)
    assert usuario.es_demo is True
    assert verify_password(CLAVE, usuario.password_hash)


def test_actualizar_clave_de_correo_inexistente(sesion, teclear):
    pedidos = teclear()

    with pytest.raises(SystemExit, match="No existe una cuenta"):
        m.main(["--correo", "nadie@ejemplo.pe", "--actualizar-clave"], sesion=sesion)

    assert pedidos == [] and usuarios(sesion) == []


# --- Validaciones ---------------------------------------------------------------------------


@pytest.mark.parametrize("rol", ["admin", "supervisor", "ciudadano", "", None])
def test_rol_invalido(sesion, teclear, rol):
    pedidos = teclear()

    with pytest.raises(SystemExit, match="Rol inválido"):
        crear(sesion, rol=rol)

    assert pedidos == [] and usuarios(sesion) == []


def test_rol_en_mayusculas_se_acepta(sesion, teclear):
    teclear(CLAVE, CLAVE)

    crear(sesion, rol="Conductor")

    assert usuarios(sesion)[0].rol == "conductor"


@pytest.mark.parametrize("correo", ["ana", "ana@", "@ejemplo.pe", "ana perez@ejemplo.pe", "ana@@ejemplo.pe"])
def test_correo_invalido(sesion, teclear, correo):
    pedidos = teclear()

    with pytest.raises(SystemExit, match="Correo inválido"):
        crear(sesion, correo=correo)

    assert pedidos == [] and usuarios(sesion) == []


def test_falta_nombre(sesion, teclear):
    teclear()

    with pytest.raises(SystemExit, match="Falta --nombre"):
        crear(sesion, nombre="   ")


def test_contrasenas_que_no_coinciden(sesion, teclear):
    teclear(CLAVE, CLAVE + "-distinta")

    with pytest.raises(SystemExit, match="no coinciden"):
        crear(sesion)

    assert usuarios(sesion) == []


@pytest.mark.parametrize(
    ("clave", "motivo"),
    [("corta", "al menos 8"), ("        ", "solo espacios"), ("ñ" * 40, "72 bytes")],
)
def test_contrasena_invalida(sesion, teclear, clave, motivo):
    pedidos = teclear(clave, clave)

    with pytest.raises(SystemExit, match=motivo):
        crear(sesion)

    assert len(pedidos) == 1  # no pide confirmar una contraseña que ya es inválida
    assert usuarios(sesion) == []


def test_cancelar_con_ctrl_c_no_guarda(sesion, monkeypatch):
    def interrumpir(prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr(m.getpass, "getpass", interrumpir)

    with pytest.raises(SystemExit, match="Cancelado"):
        crear(sesion)

    assert usuarios(sesion) == []


def test_no_acepta_la_contrasena_por_argumento(sesion):
    with pytest.raises(SystemExit):  # argparse: argumento desconocido
        m.main(["--correo", "a@ejemplo.pe", "--nombre", "A", "--rol", "conductor", "--password", CLAVE],
               sesion=sesion)

    assert usuarios(sesion) == []
