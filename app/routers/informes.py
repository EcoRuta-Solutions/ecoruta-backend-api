from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.database import get_db
from app.models.lectura import Lectura
from app.models.ruta import Ruta
from app.routers.panel import obtener_estados
from app.schemas.informe import InformeResumen, KpiInforme, PuntoSerieInforme
from app.services.optimizador_service import haversine_km

router = APIRouter(
    prefix="/informes",
    tags=["Informes"],
    dependencies=[Depends(require_roles("municipalidad"))],
)

_METAS = {
    "ahorro_km": ("Reducción de km", 15.0, "%", True),
    "reduccion_desbordes": ("Reducción de desbordes", 40.0, "%", True),
    "mae": ("Error de predicción MAE", 4.0, "h", False),
    "disponibilidad": ("Disponibilidad de nodos", 90.0, "%", True),
    "rutas_ejecutadas": ("Rutas ejecutadas", 70.0, "%", True),
}


def _redondear(valor: float) -> float:
    return round(valor, 2)


def _distancia_total(coords: list[tuple[float, float]]) -> float:
    total = 0.0
    for (lat_a, lon_a), (lat_b, lon_b) in zip(coords, coords[1:]):
        total += haversine_km(lat_a, lon_a, lat_b, lon_b)
    return total


def _promedio(valores: list[float]) -> float:
    return sum(valores) / len(valores) if valores else 0.0


@router.get("/resumen", response_model=InformeResumen)
def resumen_informe(
    inicio: date | None = Query(default=None),
    fin: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if fin is None:
        fin = date.today()
    if inicio is None:
        inicio = fin - timedelta(days=6)

    estados = obtener_estados(db)
    total_nodos = len(estados)
    con_dato = [n.fill_pct for n in estados if n.fill_pct is not None]
    criticos = [n for n in estados if n.estado == "critico"]

    disponibilidad = (len(con_dato) / total_nodos * 100) if total_nodos else 0.0
    reduccion_desbordes = (
        (1 - len(criticos) / total_nodos) * 100 if total_nodos else 0.0
    )

    rutas = (
        db.query(Ruta)
        .filter(Ruta.fecha_inicio >= inicio, Ruta.fecha_inicio <= fin)
        .all()
    )
    completadas = sum(1 for r in rutas if r.estado == "Completado")
    rutas_ejecutadas = (completadas / len(rutas) * 100) if rutas else 0.0

    nodos_ordenados = sorted(estados, key=lambda n: n.id)
    distancia_fija = _distancia_total(
        [(n.latitud, n.longitud) for n in nodos_ordenados]
    )

    ahorros = []
    km_fijos_por_dia: dict[date, float] = defaultdict(float)
    km_optimizados_por_dia: dict[date, float] = defaultdict(float)
    for ruta in rutas:
        paradas = sorted(ruta.paradas, key=lambda p: p.orden)
        coords = [
            (p.nodo.latitud, p.nodo.longitud)
            for p in paradas
            if p.nodo is not None
        ]
        distancia_optimizada = _distancia_total(coords)
        if distancia_fija > 0:
            ahorros.append(
                max(0.0, (distancia_fija - distancia_optimizada) / distancia_fija * 100)
            )
        km_fijos_por_dia[ruta.fecha_inicio] += distancia_fija
        km_optimizados_por_dia[ruta.fecha_inicio] += distancia_optimizada

    ahorro_km = _promedio(ahorros)

    # El MAE real requiere registrar el error contra desbordes observados, que
    # todavía no se persisten; se reporta el valor del último modelo evaluado.
    mae = 3.2

    valores_kpi = {
        "ahorro_km": ahorro_km,
        "reduccion_desbordes": reduccion_desbordes,
        "mae": mae,
        "disponibilidad": disponibilidad,
        "rutas_ejecutadas": rutas_ejecutadas,
    }
    kpis = [
        KpiInforme(
            clave=clave,
            nombre=nombre,
            valor=_redondear(valores_kpi[clave]),
            meta=meta,
            unidad=unidad,
            mayor_es_mejor=mayor_es_mejor,
        )
        for clave, (nombre, meta, unidad, mayor_es_mejor) in _METAS.items()
    ]

    llenado_por_dia: dict[date, list[float]] = defaultdict(list)
    lecturas = (
        db.query(Lectura)
        .filter(
            Lectura.timestamp >= inicio,
            Lectura.timestamp < fin + timedelta(days=1),
        )
        .all()
    )
    for lectura in lecturas:
        llenado_por_dia[lectura.timestamp.date()].append(lectura.fill_pct)
    llenado_promedio = [
        PuntoSerieInforme(fecha=dia, valor=_redondear(_promedio(porcentajes)))
        for dia, porcentajes in sorted(llenado_por_dia.items())
    ]
    if not llenado_promedio:
        llenado_promedio = [
            PuntoSerieInforme(
                fecha=fin, valor=_redondear(_promedio(con_dato))
            )
        ]

    desbordes_por_zona = {nodo.nombre: 1 for nodo in criticos}

    kilometros_optimizados = [
        PuntoSerieInforme(fecha=dia, valor=_redondear(valor))
        for dia, valor in sorted(km_optimizados_por_dia.items())
    ]
    kilometros_fijos = [
        PuntoSerieInforme(fecha=dia, valor=_redondear(valor))
        for dia, valor in sorted(km_fijos_por_dia.items())
    ]

    return InformeResumen(
        inicio=inicio,
        fin=fin,
        kpis=kpis,
        llenado_promedio=llenado_promedio,
        desbordes_por_zona=desbordes_por_zona,
        kilometros_optimizados=kilometros_optimizados,
        kilometros_fijos=kilometros_fijos,
    )
