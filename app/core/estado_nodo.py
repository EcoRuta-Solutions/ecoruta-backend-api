UMBRAL_ALERTA = 50


def calcular_estado(fill_pct, umbral_critico):
    if fill_pct is None:
        return "sin_datos"
    if fill_pct >= umbral_critico:
        return "critico"
    if fill_pct >= UMBRAL_ALERTA:
        return "alerta"
    return "normal"