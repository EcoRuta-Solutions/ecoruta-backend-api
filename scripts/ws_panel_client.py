import asyncio
from getpass import getpass
import os

from websockets.asyncio.client import connect

URL = "ws://127.0.0.1:8000/ws/panel"


async def main() -> None:
    token = os.getenv("ECORUTA_WS_TOKEN") or getpass("Token JWT: ")
    max_eventos = int(os.getenv("ECORUTA_WS_MAX_EVENTOS", "0"))
    try:
        async with connect(f"{URL}?token={token}") as websocket:
            print("Conectado. Esperando eventos; Ctrl+C para salir.")
            recibidos = 0
            async for mensaje in websocket:
                print(mensaje)
                recibidos += 1
                if max_eventos and recibidos >= max_eventos:
                    return
    except KeyboardInterrupt:
        print("\nCliente desconectado.")


if __name__ == "__main__":
    asyncio.run(main())