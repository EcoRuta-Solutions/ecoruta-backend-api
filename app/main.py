from fastapi import FastAPI
from app.routers import nodos

app = FastAPI(title="EcoRuta API")

app.include_router(nodos.router)


@app.get("/")
def raiz():
    return {"mensaje": "EcoRuta API funcionando"}