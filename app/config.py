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

# Optimizador de rutas por turno (POST /rutas/generar).
# Sin matriz OSRM, la distancia es haversine × este factor de circuito (aproximada).
OPTIMIZADOR_FACTOR_CIRCUITO = float(os.getenv("OPTIMIZADOR_FACTOR_CIRCUITO", "1.3"))
# Velocidad media urbana para estimar el tiempo de una ruta.
OPTIMIZADOR_VELOCIDAD_KMH = float(os.getenv("OPTIMIZADOR_VELOCIDAD_KMH", "20"))
# PROVISIONAL: minutos de recolección por parada; no hay un dato medido todavía.
OPTIMIZADOR_MINUTOS_POR_PARADA = float(os.getenv("OPTIMIZADOR_MINUTOS_POR_PARADA", "5"))
# Tiempo máximo de búsqueda de OR-Tools por generación.
OPTIMIZADOR_TIEMPO_MAX_S = int(os.getenv("OPTIMIZADOR_TIEMPO_MAX_S", "10"))
# Matriz de distancias por calles (scripts/calcular_matriz_distancias.py).
MATRIZ_DISTANCIAS_ARCHIVO = os.getenv("MATRIZ_DISTANCIAS_ARCHIVO", "data/matriz_distancias.json")
# Servidor OSRM (por defecto el público de demostración, con límites de uso).
OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org")
