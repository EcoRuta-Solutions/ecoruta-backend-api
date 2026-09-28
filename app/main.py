from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, nodos, lecturas, panel

app = FastAPI(title="EcoRuta API")

# Necesario para que Flutter Web (otro puerto) pueda llamar a la API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # solo para desarrollo; en producción, el dominio real
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(nodos.router)
app.include_router(lecturas.router)
app.include_router(panel.router)


@app.get("/")
def raiz():
    return {"mensaje": "EcoRuta API funcionando"}