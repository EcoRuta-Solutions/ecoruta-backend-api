import jwt
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, nodos, lecturas, panel, reportes
from app.core.connection_manager import connection_manager
from app.core.security import decode_token
from app.database import SessionLocal
from app.models.usuario import Usuario
from app.routers import camiones, rutas

app = FastAPI(title="EcoRuta API")

# Necesario para que Flutter Web (otro puerto) pueda llamar a la API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # solo para desarrollo; en producción, el dominio real
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(nodos.router, prefix="/nodos", tags=["nodos"])
app.include_router(lecturas.router, prefix="/lecturas", tags=["lecturas"])
app.include_router(panel.router, prefix="/panel", tags=["panel"])
app.include_router(reportes.router, prefix="/reportes", tags=["reportes"])
app.include_router(camiones.router, prefix="/camiones", tags=["camiones"])
app.include_router(rutas.router, prefix="/rutas", tags=["rutas"])


@app.websocket("/ws/panel")
async def websocket_panel(websocket: WebSocket, token: str | None = Query(default=None)):
    if not token:
        await websocket.accept()
        await websocket.close(code=1008)
        return

    db = SessionLocal()
    try:
        try:
            payload = decode_token(token)
            user_id = int(payload["sub"])
        except (jwt.PyJWTError, KeyError, ValueError):
            await websocket.accept()
            await websocket.close(code=1008)
            return

        usuario = db.get(Usuario, user_id)
        if (
            usuario is None
            or not usuario.activo
            or usuario.rol not in {"municipalidad", "conductor"}
        ):
            await websocket.accept()
            await websocket.close(code=1008)
            return
    finally:
        db.close()

    await connection_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        connection_manager.disconnect(websocket)


@app.get("/")
def raiz():
    return {"mensaje": "EcoRuta API funcionando"}