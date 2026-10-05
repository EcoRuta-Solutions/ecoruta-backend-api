import os
import sys
import uuid
from pathlib import Path

os.environ["PYTHON_DOTENV_DISABLED"] = "true"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

variables_requeridas = ("DATABASE_URL", "SECRET_KEY", "DEVICE_API_KEY")
variables_faltantes = [nombre for nombre in variables_requeridas if not os.getenv(nombre)]
if variables_faltantes:
    raise SystemExit("Faltan variables de entorno: " + ", ".join(variables_faltantes))

import requests

from app.core.security import create_access_token
from app.database import SessionLocal
from app.models.usuario import Usuario

API_URL = os.getenv("ECORUTA_API_URL", "http://127.0.0.1:8000").rstrip("/")


def verificar(nombre: str, respuesta: requests.Response, esperado: int) -> requests.Response:
    if respuesta.status_code != esperado:
        raise AssertionError(
            f"{nombre}: se esperaba HTTP {esperado}, se recibió "
            f"{respuesta.status_code}: {respuesta.text}"
        )
    print(f"OK {nombre}: HTTP {esperado}")
    return respuesta


def main() -> None:
    db = SessionLocal()
    try:
        cuentas = {
            "municipalidad": "municipalidad2@ecoruta.test",
            "conductor": "conductor@ecoruta.test",
            "ciudadano": "ciudadano@ecoruta.test",
        }
        usuarios = {
            rol: db.query(Usuario).filter(Usuario.email == email).first()
            for rol, email in cuentas.items()
        }
        faltantes = [rol for rol, usuario in usuarios.items() if usuario is None]
        if faltantes:
            raise SystemExit("Faltan usuarios de prueba para los roles: " + ", ".join(faltantes))
        tokens = {
            rol: create_access_token(usuario.id, usuario.rol)
            for rol, usuario in usuarios.items()
        }
    finally:
        db.close()

    headers = {
        rol: {"Authorization": f"Bearer {token}"}
        for rol, token in tokens.items()
    }
    base = API_URL

    verificar("raíz pública", requests.get(base + "/", timeout=5), 200)
    verificar("/auth/me con token", requests.get(base + "/auth/me", headers=headers["ciudadano"], timeout=5), 200)
    verificar("/auth/me sin token", requests.get(base + "/auth/me", timeout=5), 401)

    reporte = verificar(
        "ciudadano crea reporte",
        requests.post(
            base + "/reportes",
            headers=headers["ciudadano"],
            json={"latitud": -8.1116, "longitud": -79.0288, "descripcion": "Verificación API " + uuid.uuid4().hex[:8]},
            timeout=5,
        ),
        201,
    ).json()
    reporte_id = reporte["id"]
    for rol in ("municipalidad", "conductor"):
        verificar(
            f"{rol} no crea reportes",
            requests.post(base + "/reportes", headers=headers[rol], json={"latitud": 0, "longitud": 0, "descripcion": "Prueba"}, timeout=5),
            403,
        )
    verificar("crear reporte sin token", requests.post(base + "/reportes", json={"latitud": 0, "longitud": 0, "descripcion": "Prueba"}, timeout=5), 401)
    verificar("crear reporte inválido", requests.post(base + "/reportes", headers=headers["ciudadano"], json={"latitud": 91, "longitud": 0, "descripcion": "Prueba"}, timeout=5), 422)

    for url in (base + "/reportes", base + "/reportes?estado=pendiente", base + "/reportes?estado=atendido"):
        verificar(f"municipalidad GET {url.removeprefix(base)}", requests.get(url, headers=headers["municipalidad"], timeout=5), 200)
    verificar("filtro de estado inválido", requests.get(base + "/reportes?estado=otro", headers=headers["municipalidad"], timeout=5), 422)
    for rol in ("ciudadano", "conductor"):
        verificar(f"{rol} no lista reportes", requests.get(base + "/reportes", headers=headers[rol], timeout=5), 403)
    verificar("GET reportes sin token", requests.get(base + "/reportes", timeout=5), 401)

    patch_url = f"{base}/reportes/{reporte_id}"
    actualizado = verificar("PATCH atendido", requests.patch(patch_url, headers=headers["municipalidad"], json={"estado": "atendido"}, timeout=5), 200)
    assert actualizado.json()["estado"] == "atendido"
    verificar("PATCH repetido idempotente", requests.patch(patch_url, headers=headers["municipalidad"], json={"estado": "atendido"}, timeout=5), 200)
    verificar("PATCH sin token", requests.patch(patch_url, json={"estado": "atendido"}, timeout=5), 401)
    verificar("PATCH id inexistente", requests.patch(base + "/reportes/2147483647", headers=headers["municipalidad"], json={"estado": "atendido"}, timeout=5), 404)
    for rol in ("ciudadano", "conductor"):
        verificar(f"{rol} no modifica reportes", requests.patch(patch_url, headers=headers[rol], json={"estado": "atendido"}, timeout=5), 403)

    for rol in ("municipalidad", "conductor"):
        verificar(f"GET nodos {rol}", requests.get(base + "/nodos/", headers=headers[rol], timeout=5), 200)
    verificar("GET nodos ciudadano", requests.get(base + "/nodos/", headers=headers["ciudadano"], timeout=5), 403)
    verificar("GET nodos sin token", requests.get(base + "/nodos/", timeout=5), 401)

    codigo = "VER-" + uuid.uuid4().hex[:10]
    nodo = verificar(
        "municipalidad crea nodo de prueba",
        requests.post(base + "/nodos/", headers=headers["municipalidad"], json={"codigo": codigo, "nombre": "Verificación API", "latitud": -8.11, "longitud": -79.02}, timeout=5),
        201,
    ).json()
    for rol in ("conductor", "ciudadano"):
        verificar(f"{rol} no crea nodos", requests.post(base + "/nodos/", headers=headers[rol], json={"codigo": codigo + rol[:1], "nombre": "Prueba", "latitud": 0, "longitud": 0}, timeout=5), 403)
    verificar("POST nodo sin token", requests.post(base + "/nodos/", json={"codigo": codigo + "X", "nombre": "Prueba", "latitud": 0, "longitud": 0}, timeout=5), 401)

    verificar("POST lectura sin X-API-Key", requests.post(base + "/lecturas/", json={"codigo": codigo, "fill_pct": 25}, timeout=5), 401)
    verificar(
        "POST lectura con X-API-Key",
        requests.post(base + "/lecturas/", headers={"X-API-Key": os.environ["DEVICE_API_KEY"]}, json={"codigo": codigo, "fill_pct": 25}, timeout=5),
        201,
    )
    verificar("POST lectura inválida", requests.post(base + "/lecturas/", headers={"X-API-Key": os.environ["DEVICE_API_KEY"]}, json={"codigo": codigo, "fill_pct": 101}, timeout=5), 422)
    historial = f"{base}/nodos/{nodo['id']}/lecturas"
    for rol in ("municipalidad", "conductor"):
        verificar(f"historial {rol}", requests.get(historial, headers=headers[rol], timeout=5), 200)
    verificar("historial ciudadano", requests.get(historial, headers=headers["ciudadano"], timeout=5), 403)
    verificar("historial sin token", requests.get(historial, timeout=5), 401)
    verificar("historial con id inválido", requests.get(base + "/nodos/no-es-id/lecturas", headers=headers["conductor"], timeout=5), 422)

    for endpoint in ("estado", "criticos", "resumen"):
        for rol in ("municipalidad", "conductor"):
            verificar(f"panel {endpoint} {rol}", requests.get(f"{base}/panel/{endpoint}", headers=headers[rol], timeout=5), 200)
        verificar(f"panel {endpoint} ciudadano", requests.get(f"{base}/panel/{endpoint}", headers=headers["ciudadano"], timeout=5), 403)
        verificar(f"panel {endpoint} sin token", requests.get(f"{base}/panel/{endpoint}", timeout=5), 401)

    print("Verificación HTTP completada. Los reportes y el nodo de prueba permanecen en la base local.")


if __name__ == "__main__":
    main()