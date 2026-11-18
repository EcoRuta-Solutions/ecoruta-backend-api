r"""Simula el sensor del contenedor prototipo (plan B si el ESP32 falla).

Envía lecturas en rampa (por defecto de 10 % a 100 % de 10 en 10) a
POST /sensores/lecturas, igual que lo haría el ESP32. La clave del dispositivo se
toma de la variable de entorno DEVICE_API_KEY o, si no está, del archivo .env;
nunca se imprime.

Son lecturas SIMULADAS: úsalo solo para la demo o para probar, nunca como dato real.

Uso:
    .\venv\Scripts\python.exe scripts\simular_sensor.py
    .\venv\Scripts\python.exe scripts\simular_sensor.py --url http://127.0.0.1:8000 --codigo PROTO-UTP --desde 10 --hasta 100 --paso 10 --intervalo 5
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def leer_clave() -> str:
    clave = os.environ.get("DEVICE_API_KEY")
    if not clave:
        from dotenv import dotenv_values

        clave = dotenv_values(RAIZ / ".env").get("DEVICE_API_KEY")
    if not clave:
        raise SystemExit("ERROR: define DEVICE_API_KEY en el entorno o en el .env")
    return clave


def niveles(desde: float, hasta: float, paso: float) -> list[float]:
    if paso <= 0:
        raise ValueError("--paso debe ser mayor que 0")
    if not (0 <= desde <= 120 and 0 <= hasta <= 120):
        raise ValueError("--desde y --hasta deben estar entre 0 y 120")
    signo = 1 if hasta >= desde else -1
    valores, actual = [], desde
    while (actual <= hasta) if signo > 0 else (actual >= hasta):
        valores.append(round(actual, 2))
        actual += signo * paso
    if valores[-1] != hasta:
        valores.append(hasta)
    return valores


def enviar(url: str, clave: str, codigo: str, nivel: float, timeout: float = 10) -> tuple[int, dict | str]:
    cuerpo = json.dumps({"codigo": codigo, "nivel_pct": nivel}).encode()
    peticion = urllib.request.Request(
        url.rstrip("/") + "/sensores/lecturas",
        data=cuerpo,
        method="POST",
        headers={"Content-Type": "application/json", "X-API-Key": clave},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            return respuesta.status, json.load(respuesta)
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")[:200]


def main(argv: list[str] | None = None, dormir=time.sleep) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--codigo", default="PROTO-UTP")
    parser.add_argument("--desde", type=float, default=10)
    parser.add_argument("--hasta", type=float, default=100)
    parser.add_argument("--paso", type=float, default=10)
    parser.add_argument("--intervalo", type=float, default=5, help="Segundos entre lecturas")
    args = parser.parse_args(argv)

    try:
        lista = niveles(args.desde, args.hasta, args.paso)
    except ValueError as error:
        raise SystemExit(f"ERROR: {error}")
    clave = leer_clave()

    print(f"Simulando {args.codigo}: {lista[0]} -> {lista[-1]} % cada {args.intervalo} s (lecturas SIMULADAS)")
    errores = 0
    for i, nivel in enumerate(lista):
        try:
            estado, cuerpo = enviar(args.url, clave, args.codigo, nivel)
        except (urllib.error.URLError, OSError) as error:
            print(f"  {nivel:6.1f} %  -> sin conexión: {error}")
            errores += 1
        else:
            if estado == 201:
                extra = f"  ALERTA: {cuerpo['alerta_creada']['mensaje']}" if cuerpo.get("alerta_creada") else ""
                print(f"  {nivel:6.1f} %  -> {cuerpo['estado_llenado']}{extra}")
            else:
                print(f"  {nivel:6.1f} %  -> HTTP {estado}: {cuerpo}")
                errores += 1
        if i < len(lista) - 1:
            dormir(args.intervalo)
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
