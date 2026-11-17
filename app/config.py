import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")
DEVICE_API_KEY = os.getenv("DEVICE_API_KEY")
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "480"))

# Reportes de campo (llenado de puntos críticos capturado por conductores/supervisores).
# Un reporte con GPS a más de esta distancia del punto se marca lejos_del_punto (no se rechaza).
REPORTE_DISTANCIA_MAX_M = float(os.getenv("REPORTE_DISTANCIA_MAX_M", "150"))
# El último reporte de un punto vale como estado actual durante estas horas; luego, "sin_datos".
REPORTE_VIGENCIA_HORAS = float(os.getenv("REPORTE_VIGENCIA_HORAS", "24"))
