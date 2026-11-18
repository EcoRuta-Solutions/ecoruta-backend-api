"""Seguridad: ninguna credencial en el repo y cuentas demo sin contraseña en el código."""

import re
import subprocess
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.security import verify_password
from app.models.usuario import Usuario
from conftest import _cargar_script

RAIZ = Path(__file__).resolve().parents[1]
demo = _cargar_script("crear_usuarios_demo")

CLAVE_DEMO = "Clave-demo-de-prueba-789"  # solo para estas pruebas

# URL de base de datos con usuario:clave@ que no sea el marcador USUARIO:CLAVE.
URL_CON_CLAVE = re.compile(r"postgres(?:ql)?(?:\+\w+)?://(?!USUARIO:CLAVE@)[^:/\s'\"]+:[^@\s'\"]+@")
# Asignación literal de una clave en código (PASSWORD = "...", SECRET_KEY = '...').
CLAVE_LITERAL = re.compile(
    r"""^\s*(?:[A-Z_]*PASSWORD|SECRET_KEY|DEVICE_API_KEY)\s*=\s*["'][^"']+["']""", re.M
)
# Texto tipo "contraseña: xxxx" o "password: xxxx" (credenciales escritas en docs/docstrings).
CREDENCIAL_EN_TEXTO = re.compile(r"(?i)(?:contrase[nñ]a|password)\s*[:=]\s*`?[A-Za-z0-9_\-]{6,}`?\s*\)?\s*$", re.M)


def archivos_versionados() -> list[Path]:
    salida = subprocess.run(
        ["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=True
    ).stdout.split()
    return [RAIZ / n for n in salida if not n.endswith((".csv", ".json", ".pkl", ".joblib", ".png"))]


def test_env_no_esta_versionado_y_hay_env_example():
    nombres = {p.relative_to(RAIZ).as_posix() for p in archivos_versionados()}

    assert ".env" not in nombres
    assert not any(re.fullmatch(r"(.*/)?\.env(\..+)?", n) and n != ".env.example" for n in nombres)
    assert ".env.example" in nombres


def test_gitignore_excluye_env_y_respaldos():
    ignorados = subprocess.run(
        ["git", "check-ignore", ".env", ".env.local", "respaldo.sql"],
        cwd=RAIZ, capture_output=True, text=True,
    ).stdout.split()

    assert ignorados == [".env", ".env.local", "respaldo.sql"]
    no_ignorado = subprocess.run(["git", "check-ignore", "-q", ".env.example"], cwd=RAIZ)
    assert no_ignorado.returncode == 1  # .env.example sí se versiona


def test_ningun_archivo_versionado_tiene_credenciales():
    hallazgos = []
    for ruta in archivos_versionados():
        if ruta.name in ("test_credenciales.py", ".env.example"):
            continue  # .env.example tiene su propia prueba (solo marcadores)
        try:
            texto = ruta.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        es_prueba = ruta.parts[-2] == "tests"
        for patron in (URL_CON_CLAVE, CLAVE_LITERAL, CREDENCIAL_EN_TEXTO):
            if es_prueba and patron is not URL_CON_CLAVE:
                continue  # las pruebas usan claves de prueba propias
            for m in patron.finditer(texto):
                linea = texto[: m.start()].count("\n") + 1
                hallazgos.append(f"{ruta.relative_to(RAIZ)}:{linea}")
    assert hallazgos == [], f"Posibles credenciales en: {hallazgos}"


def test_env_example_solo_tiene_marcadores():
    valores = dict(
        linea.split("=", 1)
        for linea in (RAIZ / ".env.example").read_text(encoding="utf-8").splitlines()
        if "=" in linea and not linea.lstrip().startswith("#")
    )

    assert "USUARIO:CLAVE@" in valores["DATABASE_URL"]
    assert valores["SECRET_KEY"] == valores["DEVICE_API_KEY"] == "GENERAR_CON_SECRETS_TOKEN_HEX"
    assert valores["POSTGRES_PASSWORD"] == "CLAVE"
    assert valores["SIMULADOR_PASSWORD"] == "CLAVE_DE_ESA_CUENTA"
    assert "ECORUTA_DEMO_PASSWORD" not in valores  # solo comentada, sin valor


def test_docker_compose_toma_la_clave_del_env():
    compose = (RAIZ / "docker-compose.yml").read_text(encoding="utf-8")

    assert "${POSTGRES_PASSWORD:?" in compose
    assert '"127.0.0.1:5433:5432"' in compose


# --- crear_usuarios_demo.py ---------------------------------------------------------------


@pytest.fixture
def sesion(db_limpia):
    return sessionmaker(bind=db_limpia, autoflush=False)


def hashes(sesion):
    with sesion() as db:
        return {u.email: u for u in db.query(Usuario)}


def test_demo_no_tiene_contrasena_en_el_codigo():
    assert not hasattr(demo, "PASSWORD")


def test_demo_toma_la_clave_de_la_variable_de_entorno(sesion, db_limpia, monkeypatch, capsys):
    monkeypatch.setenv("ECORUTA_DEMO_PASSWORD", CLAVE_DEMO)
    monkeypatch.setattr("getpass.getpass", lambda *_: pytest.fail("no debía pedir por consola"))

    demo.main(sesion=sesion, engine=db_limpia)

    cuentas = hashes(sesion)
    assert set(cuentas) == {"conductor@ecoruta.com", "municipalidad3@ecoruta.com"}
    assert all(u.es_demo and u.activo and verify_password(CLAVE_DEMO, u.password_hash) for u in cuentas.values())
    salida = capsys.readouterr()
    assert CLAVE_DEMO not in salida.out + salida.err


def test_demo_pide_la_clave_por_consola_si_no_hay_variable(sesion, db_limpia, monkeypatch, capsys):
    monkeypatch.delenv("ECORUTA_DEMO_PASSWORD", raising=False)
    respuestas = iter([CLAVE_DEMO, CLAVE_DEMO])
    monkeypatch.setattr("getpass.getpass", lambda *_: next(respuestas))

    demo.main(sesion=sesion, engine=db_limpia)

    assert all(verify_password(CLAVE_DEMO, u.password_hash) for u in hashes(sesion).values())
    assert CLAVE_DEMO not in capsys.readouterr().out


@pytest.mark.parametrize("clave", ["corta", "        "])
def test_demo_rechaza_clave_debil_sin_crear_nada(sesion, db_limpia, monkeypatch, clave):
    monkeypatch.setenv("ECORUTA_DEMO_PASSWORD", clave)

    with pytest.raises(SystemExit, match="ERROR"):
        demo.main(sesion=sesion, engine=db_limpia)

    assert hashes(sesion) == {}
