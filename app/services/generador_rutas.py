"""Genera las rutas de un turno sobre datos reales: puntos críticos y flota.

- Puntos: puntos_criticos (todos, o solo los de priorización obligatoria, o solo
  los que tienen un reporte de campo vigente lleno/desbordado).
- Camiones: los del turno en estado operativo, activos y no demo (más las
  reservas si se pide). Sin camiones -> SinCamiones (409); no se inventan.
- Reparto: por número de paradas, máx. ceil(N / camiones) por ruta, minimizando
  distancia. No hay peso por punto: la capacidad del camión NO se usa como
  restricción (además está sin confirmar).
- No hay base/relleno confirmados: la distancia es la del recorrido entre
  puntos, sin el viaje de ida ni de vuelta.
- Regenerar reemplaza solo las rutas "Pendiente" generadas para ese turno y
  fecha. Las rutas en curso o completadas no se tocan, y sus camiones y puntos
  quedan fuera del nuevo reparto.
"""

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.core.turnos import Turno, normalizar_turno, turno_de_hora
from app.models.camion import Camion, EstadoCamion
from app.models.conductor import Conductor
from app.models.punto_critico import PuntoCritico
from app.models.reporte_campo import EstadoReporte
from app.models.ruta import Parada, Ruta
from app.services import reportes_service
from app.services.distancias_service import METODO_OSRM, Punto, matriz_para_puntos
from app.services.flota_service import filtrar_camiones
from app.services.optimizador_service import distancia_camino_km, repartir_en_rutas

ESTADO_PENDIENTE = "pendiente"
# Rutas que ya empezaron o terminaron: no se reemplazan.
ESTADOS_EN_CURSO = {"en_proceso", "completado"}
ESTADOS_LLENOS = {EstadoReporte.lleno.value, EstadoReporte.desbordado.value}


class SinCamiones(Exception):
    pass


class SinPuntos(Exception):
    pass


class ParametroInvalido(Exception):
    pass


@dataclass
class PuntoGenerado:
    id: int
    codigo: str
    lat: float
    lon: float
    direccion: str


@dataclass
class RutaGenerada:
    ruta: Ruta
    camion: Camion
    paradas: list[PuntoGenerado]
    excede_turno: bool


@dataclass
class ResultadoGeneracion:
    turno: Turno
    fecha: date
    nro_camiones: int
    nro_puntos: int
    max_paradas_por_ruta: int
    metodo_distancia: str
    rutas: list[RutaGenerada] = field(default_factory=list)
    rutas_reemplazadas: int = 0
    camiones_con_ruta_en_curso: list[str] = field(default_factory=list)

    @property
    def distancia_total_km(self) -> float:
        return sum(r.ruta.distancia_km for r in self.rutas)


def _rutas_del_turno(db: Session, turno: Turno, fecha: date) -> list[Ruta]:
    return (
        db.query(Ruta)
        .filter(Ruta.turno == turno.value, Ruta.fecha_inicio == fecha, Ruta.es_demo.is_(False))
        .all()
    )


def _camiones(db: Session, turno: Turno, incluir_reserva: bool) -> list[Camion]:
    estados = [EstadoCamion.operativo.value]
    if incluir_reserva:
        estados.append(EstadoCamion.reserva.value)
    return (
        filtrar_camiones(db.query(Camion), turno)
        .filter(
            Camion.estado.in_(estados),
            Camion.es_demo.is_(False),
            Camion.activo.is_(True),
        )
        .order_by(Camion.id)
        .all()
    )


def _puntos(
    db: Session,
    solo_prioritarios: bool,
    solo_con_reporte_lleno: bool,
    incluir_prototipos: bool = False,
) -> list[PuntoGenerado]:
    """Puntos a recolectar. Los de prototipo solo entran si se pide (ruta del conductor)."""
    ultimo = reportes_service.ultimo_reporte_por_punto()
    consulta = (
        select(
            PuntoCritico.id,
            PuntoCritico.codigo_unico,
            func.ST_Y(PuntoCritico.ubicacion),
            func.ST_X(PuntoCritico.ubicacion),
            PuntoCritico.direccion,
            ultimo.c.estado,
            ultimo.c.creado_en,
            ultimo.c.origen,
        )
        .outerjoin(ultimo, ultimo.c.punto_critico_id == PuntoCritico.id)
        .order_by(PuntoCritico.id)
    )
    if not incluir_prototipos:
        consulta = consulta.where(PuntoCritico.es_prototipo.is_(False))
    if solo_prioritarios:
        consulta = consulta.where(PuntoCritico.priorizacion_obligatoria.is_(True))

    momento = reportes_service.ahora()
    puntos = []
    for id_, codigo, lat, lon, direccion, estado, creado_en, origen in db.execute(consulta):
        if solo_con_reporte_lleno and (
            reportes_service.estado_llenado(estado, creado_en, momento, origen)
            not in ESTADOS_LLENOS
        ):
            continue
        puntos.append(PuntoGenerado(id_, codigo, lat, lon, direccion))
    return puntos


def _conductor_de(db: Session, camion: Camion) -> int | None:
    """Usuario del conductor asignado a este camión (conductores.camion_id), si hay."""
    return db.scalar(
        select(Conductor.usuario_id)
        .where(
            Conductor.camion_id == camion.id,
            Conductor.usuario_id.is_not(None),
            Conductor.activo.is_(True),
        )
        .order_by(Conductor.id)
        .limit(1)
    )


def generar_rutas_turno(
    db: Session,
    turno: Turno,
    fecha: date,
    solo_prioritarios: bool = False,
    solo_con_reporte_lleno: bool = False,
    incluir_reserva: bool = False,
    max_paradas_por_ruta: int | None = None,
) -> ResultadoGeneracion:
    existentes = _rutas_del_turno(db, turno, fecha)
    en_curso = [r for r in existentes if r.estado.strip().lower() in ESTADOS_EN_CURSO]
    pendientes = [r for r in existentes if r.estado.strip().lower() == ESTADO_PENDIENTE]
    camiones_ocupados = {r.camion_id for r in en_curso}
    puntos_ocupados = {p.punto_critico_id for r in en_curso for p in r.paradas}

    todos_camiones = _camiones(db, turno, incluir_reserva)
    camiones = [c for c in todos_camiones if c.id not in camiones_ocupados]
    if not todos_camiones:
        raise SinCamiones(
            f"No hay camiones operativos (no demo) en el turno {turno.value}. "
            "Carga o confirma la flota del turno; no se inventan camiones."
        )
    if not camiones:
        raise SinCamiones(
            f"Todos los camiones del turno {turno.value} ya tienen una ruta en curso "
            f"o completada el {fecha.isoformat()}."
        )

    puntos = [
        p for p in _puntos(db, solo_prioritarios, solo_con_reporte_lleno)
        if p.id not in puntos_ocupados
    ]
    if not puntos:
        raise SinPuntos("No hay puntos críticos que cumplan los filtros")

    minimo = math.ceil(len(puntos) / len(camiones))
    if max_paradas_por_ruta is None:
        max_paradas_por_ruta = minimo
    elif max_paradas_por_ruta < minimo:
        raise ParametroInvalido(
            f"max_paradas_por_ruta debe ser al menos {minimo} "
            f"({len(puntos)} puntos entre {len(camiones)} camiones)"
        )

    matriz = matriz_para_puntos([Punto(p.codigo, p.lat, p.lon) for p in puntos])
    try:
        reparto = repartir_en_rutas(
            matriz.km, len(camiones), max_paradas_por_ruta, config.OPTIMIZADOR_TIEMPO_MAX_S
        )
    except (ValueError, RuntimeError) as error:
        raise ParametroInvalido(str(error))

    # Solo se escribe cuando el reparto salió bien.
    for ruta in pendientes:
        db.delete(ruta)  # cascade borra sus paradas
    db.flush()

    inicio = datetime.combine(fecha, turno.inicio)
    fin_turno = datetime.combine(fecha, turno.fin)
    if turno.cruza_medianoche:
        fin_turno += timedelta(days=1)

    resultado = ResultadoGeneracion(
        turno=turno,
        fecha=fecha,
        nro_camiones=len(camiones),
        nro_puntos=len(puntos),
        max_paradas_por_ruta=max_paradas_por_ruta,
        metodo_distancia=matriz.metodo,
        rutas_reemplazadas=len(pendientes),
        camiones_con_ruta_en_curso=sorted(
            c.placa for c in todos_camiones if c.id in camiones_ocupados
        ),
    )
    for camion, orden in zip(camiones, reparto):
        if not orden:
            continue
        distancia = distancia_camino_km(matriz.km, orden)
        minutos = (
            distancia / config.OPTIMIZADOR_VELOCIDAD_KMH * 60
            + len(orden) * config.OPTIMIZADOR_MINUTOS_POR_PARADA
        )
        fin = inicio + timedelta(minutes=minutos)
        ruta = Ruta(
            fecha_inicio=fecha,
            fecha_fin=fin.date(),
            hora_inicio=inicio,
            hora_fin=fin,
            camion_id=camion.id,
            conductor_id=_conductor_de(db, camion),
            estado="Pendiente",
            es_demo=False,
            turno=turno.value,
            distancia_km=round(distancia, 3),
            tiempo_estimado_min=round(minutos, 1),
            metodo_distancia=matriz.metodo,
        )
        db.add(ruta)
        db.flush()
        paradas = [puntos[i] for i in orden]
        for posicion, punto in enumerate(paradas, start=1):
            db.add(Parada(ruta_id=ruta.id, punto_critico_id=punto.id, orden=posicion))
        resultado.rutas.append(RutaGenerada(ruta, camion, paradas, fin > fin_turno))

    db.commit()
    return resultado


def parametros_usados(metodo: str) -> dict:
    """Parámetros del cálculo, marcando los provisionales (no medidos)."""
    return {
        "velocidad_media_kmh": config.OPTIMIZADOR_VELOCIDAD_KMH,
        "minutos_por_parada": config.OPTIMIZADOR_MINUTOS_POR_PARADA,
        "factor_circuito": (
            config.OPTIMIZADOR_FACTOR_CIRCUITO if metodo != METODO_OSRM else None
        ),
        "capacidad_camion_usada": False,
        "provisionales": [
            "minutos_por_parada",
            "velocidad_media_kmh",
            *(["factor_circuito"] if metodo != METODO_OSRM else []),
        ],
        "notas": [
            "El reparto se equilibra por número de paradas: no hay peso por punto.",
            "La capacidad de los camiones no se usa (sin confirmar y sin pesos por punto).",
            "La distancia no incluye el viaje desde la base ni hasta el relleno (ubicaciones sin confirmar).",
        ],
    }


# --- Ruta del conductor (POST /rutas/generar-mia) -----------------------------------------


class SinCamionAsignado(Exception):
    pass


class RutaEnCurso(Exception):
    pass


@dataclass
class ResultadoRutaConductor:
    ruta: RutaGenerada
    nro_puntos: int
    metodo_distancia: str
    rutas_reemplazadas: int


def generar_ruta_conductor(db: Session, usuario_id: int, fecha: date, ahora: datetime) -> ResultadoRutaConductor:
    """Una ruta para el camión del conductor con TODOS los puntos lleno/desbordado vigentes.

    - El camión sale de conductores.camion_id del conductor activo de ese usuario.
    - Si el camión ya tiene una ruta en curso hoy -> RutaEnCurso (409).
    - Si tiene rutas pendientes hoy, se reemplazan.
    - Sin puntos llenos -> SinPuntos (422).
    - Sin tope de paradas: un solo camión recorre todos los puntos llenos.
    - Incluye los puntos de prototipo (sensor) y deja conductor_id = usuarios.id.
    """
    conductor = (
        db.query(Conductor)
        .filter(
            Conductor.usuario_id == usuario_id,
            Conductor.activo.is_(True),
            Conductor.camion_id.is_not(None),
        )
        .order_by(Conductor.id)
        .first()
    )
    if conductor is None:
        raise SinCamionAsignado(
            "No tienes un camión asignado. Pide a la municipalidad que te vincule a uno."
        )
    camion = db.get(Camion, conductor.camion_id)

    de_hoy = db.query(Ruta).filter(Ruta.camion_id == camion.id, Ruta.fecha_inicio == fecha).all()
    if any(r.estado.strip().lower() == "en_proceso" for r in de_hoy):
        raise RutaEnCurso(
            f"El camión {camion.placa} ya tiene una ruta en proceso hoy. "
            "Termínala antes de generar otra."
        )
    pendientes = [r for r in de_hoy if r.estado.strip().lower() == ESTADO_PENDIENTE]

    puntos = _puntos(db, solo_prioritarios=False, solo_con_reporte_lleno=True, incluir_prototipos=True)
    if not puntos:
        raise SinPuntos("No hay puntos llenos ni desbordados con un reporte vigente para recolectar.")

    matriz = matriz_para_puntos(
        [Punto(p.codigo, p.lat, p.lon) for p in puntos], permitir_mixta=True
    )
    try:
        [orden] = repartir_en_rutas(matriz.km, 1, len(puntos), config.OPTIMIZADOR_TIEMPO_MAX_S)
    except (ValueError, RuntimeError) as error:
        raise ParametroInvalido(str(error))

    for ruta in pendientes:
        db.delete(ruta)
    db.flush()

    turno = normalizar_turno(camion.turno) or turno_de_hora(ahora.time())
    distancia = distancia_camino_km(matriz.km, orden)
    minutos = (
        distancia / config.OPTIMIZADOR_VELOCIDAD_KMH * 60
        + len(orden) * config.OPTIMIZADOR_MINUTOS_POR_PARADA
    )
    inicio = ahora.replace(second=0, microsecond=0, tzinfo=None)
    fin = inicio + timedelta(minutes=minutos)
    fin_turno = datetime.combine(fecha, turno.fin)
    if turno.cruza_medianoche and turno.fin <= inicio.time():
        fin_turno += timedelta(days=1)

    ruta = Ruta(
        fecha_inicio=fecha,
        fecha_fin=fin.date(),
        hora_inicio=inicio,
        hora_fin=fin,
        camion_id=camion.id,
        conductor_id=usuario_id,  # usuarios.id, igual que el generador por turno
        estado="Pendiente",
        es_demo=False,
        turno=turno.value,
        distancia_km=round(distancia, 3),
        tiempo_estimado_min=round(minutos, 1),
        metodo_distancia=matriz.metodo,
    )
    db.add(ruta)
    db.flush()
    paradas = [puntos[i] for i in orden]
    for posicion, punto in enumerate(paradas, start=1):
        db.add(Parada(ruta_id=ruta.id, punto_critico_id=punto.id, orden=posicion))
    db.commit()

    return ResultadoRutaConductor(
        ruta=RutaGenerada(ruta, camion, paradas, fin > fin_turno),
        nro_puntos=len(puntos),
        metodo_distancia=matriz.metodo,
        rutas_reemplazadas=len(pendientes),
    )
