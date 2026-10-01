import os
import random
import time
import requests
from dotenv import load_dotenv

load_dotenv()

API = "http://127.0.0.1:8000"
SEGUNDOS_ENTRE_LECTURAS = 3

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


def obtener_clave_dispositivo():
    clave = os.getenv("DEVICE_API_KEY")
    if not clave:
        raise SystemExit("Falta la variable de entorno DEVICE_API_KEY para el simulador.")
    return clave


def iniciar_sesion_municipal():
    email = os.getenv("SIMULADOR_EMAIL")
    password = os.getenv("SIMULADOR_PASSWORD")
    faltantes = [
        nombre
        for nombre, valor in (
            ("SIMULADOR_EMAIL", email),
            ("SIMULADOR_PASSWORD", password),
        )
        if not valor
    ]
    if faltantes:
        raise SystemExit(
            "Faltan variables de entorno requeridas para el simulador: "
            + ", ".join(faltantes)
        )

    try:
        respuesta = requests.post(
            f"{API}/auth/login",
            data={"username": email, "password": password},
            timeout=5,
        )
        respuesta.raise_for_status()
    except requests.RequestException as error:
        raise SystemExit(f"No se pudo iniciar sesión como municipalidad: {error}") from error

    token = respuesta.json().get("access_token")
    if not token:
        raise SystemExit("El login municipal no devolvió un token de acceso.")
    return token


def crear_nodos(token):
    """Registra los nodos en la API. Si ya existen (409), los deja como están."""
    for nodo in NODOS:
        r = requests.post(
            f"{API}/nodos/",
            json=nodo,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
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


def enviar_lecturas(api_key):
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
            headers={"X-API-Key": api_key},
            timeout=5,
        )
        print(f"{codigo}: {medido:5.1f}%  tilt={tilt}  -> {r.status_code}")


if __name__ == "__main__":
    clave_dispositivo = obtener_clave_dispositivo()
    token_municipal = iniciar_sesion_municipal()
    crear_nodos(token_municipal)
    print("\nSimulando lecturas. Ctrl+C para detener.\n")
    try:
        while True:
            enviar_lecturas(clave_dispositivo)
            print("-" * 40)
            time.sleep(SEGUNDOS_ENTRE_LECTURAS)
    except KeyboardInterrupt:
        print("\nSimulador detenido.")