from fastapi import FastAPI
from app.routers import nodos, lecturas

app = FastAPI(title="EcoRuta API")

app.include_router(nodos.router)
app.include_router(lecturas.router)


@app.get("/")
def raiz():
    return {"mensaje": "EcoRuta API funcionando"}