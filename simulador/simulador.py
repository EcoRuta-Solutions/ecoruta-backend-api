import os
import random
import time
import requests
from dotenv import load_dotenv

load_dotenv()

API = "http://127.0.0.1:8000"
SEGUNDOS_ENTRE_LECTURAS = 3

# --- Credenciales del usuario municipalidad que crea los nodos ---
MUNICIPALIDAD_EMAIL = "municipalidad3@ecoruta.com"
MUNICIPALIDAD_PASSWORD = "Muni456"

# --- API key del dispositivo (la misma que tienes en tu .env) ---
DEVICE_API_KEY = os.getenv("DEVICE_API_KEY", "")

# Coordenadas aproximadas en Trujillo; ajústalas si quieres
NODOS = [
    {"codigo": "TRU-001", "nombre": "Plaza de Armas",     "latitud": -8.1116, "longitud": -79.0288},
    {"codigo": "TRU-002", "nombre": "Mercado Mayorista",  "latitud": -8.1150, "longitud": -79.0230},
    {"codigo": "TRU-003", "nombre": "Av. España",         "latitud": -8.1080, "longitud": -79.0250},
    {"codigo": "TRU-004", "nombre": "Óvalo Papal",        "latitud": -8.1190, "longitud": -79.0310},
    {"codigo": "TRU-005", "nombre": "Av. Larco",          "latitud": -8.1230, "longitud": -79.0350},
    {"codigo": "TRU-006", "nombre": "Parque Industrial",  "latitud": -8.1300, "longitud": -79.0200},
    {"codigo": "TRU-007", "nombre": "Mercado La Hermelinda", "latitud": -8.1020, "longitud": -79.0180},
    {"codigo": "TRU-008", "nombre": "Av. Mansiche",       "latitud": -8.1050, "longitud": -79.0400},
]


def login_municipalidad() -> dict:
    """
    Se loguea como usuario municipalidad y devuelve el header
    Authorization listo para usar en las peticiones que lo necesiten.
    """
    r = requests.post(
        f"{API}/auth/login",
        data={"username": MUNICIPALIDAD_EMAIL, "password": MUNICIPALIDAD_PASSWORD},
        timeout=5,
    )
    if r.status_code != 200:
        raise SystemExit(
            f"No se pudo loguear como municipalidad ({r.status_code}): {r.text}\n"
            "Revisa MUNICIPALIDAD_EMAIL / MUNICIPALIDAD_PASSWORD en este archivo."
        )
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def crear_nodos(auth_headers: dict):
    """Registra los nodos en la API. Si ya existen (409), los deja como están."""
    for nodo in NODOS:
        r = requests.post(f"{API}/nodos/", json=nodo, headers=auth_headers, timeout=5)
        if r.status_code == 201:
            print(f"Nodo creado: {nodo['codigo']} - {nodo['nombre']}")
        elif r.status_code == 409:
            print(f"Ya existía: {nodo['codigo']}")
        else:
            print(f"Error con {nodo['codigo']}: {r.status_code} {r.text}")


# Cada nodo tiene su propio ritmo de llenado (mercados se llenan más rápido)
estado = {
    n["codigo"]: {
        "fill": random.uniform(5, 60),
        "tasa": random.uniform(0.5, 3.0),
    }
    for n in NODOS
}


def enviar_lecturas(device_headers: dict):
    for codigo, e in estado.items():
        # El nivel sube con algo de variación
        e["fill"] += e["tasa"] * random.uniform(0.5, 1.5)

        # Si está casi lleno, a veces pasa el camión y lo vacía
        if e["fill"] >= 95 and random.random() < 0.3:
            e["fill"] = random.uniform(0, 5)

        e["fill"] = min(e["fill"], 100)

        # Ruido del sensor: nunca mide exacto
        medido = max(0, min(100, e["fill"] + random.uniform(-1.5, 1.5)))

        # 2% de las veces el nodo "falla" y no envía nada
        if random.random() < 0.02:
            print(f"{codigo}: sin señal")
            continue

        # 1% de las veces detecta que lo movieron o lo voltearon
        tilt = random.random() < 0.01

        r = requests.post(
            f"{API}/lecturas/",
            json={"codigo": codigo, "fill_pct": round(medido, 1), "tilt_alert": tilt},
            headers=device_headers,
            timeout=5,
        )
        print(f"{codigo}: {medido:5.1f}%  tilt={tilt}  -> {r.status_code}")


if __name__ == "__main__":
    if not DEVICE_API_KEY:
        raise SystemExit("No encontré DEVICE_API_KEY en tu .env. Revisa que exista esa línea.")

    auth_headers = login_municipalidad()
    device_headers = {"X-API-Key": DEVICE_API_KEY}

    crear_nodos(auth_headers)
    print("\nSimulando lecturas. Ctrl+C para detener.\n")
    try:
        while True:
            enviar_lecturas(device_headers)
            print("-" * 40)
            time.sleep(SEGUNDOS_ENTRE_LECTURAS)
    except KeyboardInterrupt:
        print("\nSimulador detenido.")