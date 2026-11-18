from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.deps import get_current_user, require_roles
from app.database import get_db
from app.models.camion import Camion
from app.models.nodo import Nodo
from app.models.ruta import Parada, Ruta
from app.models.usuario import Usuario
from app.routers.panel import obtener_estados
from app.schemas.ruta import (
    CamionRutaOut,
    ParadaGeneradaOut,
    ParadaOut,
    ParadaUpdate,
    RutaCreate,
    RutaEstadoUpdate,
    RutaGeneradaOut,
    RutaGenerarRequest,
    RutaOut,
    RutasTurnoOut,
)
from app.services import generador_rutas, reportes_service


router = APIRouter(prefix="/rutas", tags=["Rutas"])


def _validar_conductor(db: Session, conductor_id: int | None) -> None:
    if conductor_id is None:
        return

    conductor = db.get(Usuario, conductor_id)

    if conductor is None or conductor.rol != "conductor":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conductor no encontrado",
        )


_PRIORIDAD_POR_ESTADO = {
    "critico": "Crítica",
    "alerta": "Alta",
    "normal": "Media",
}


def _llenado_de_puntos(db: Session, ids: set[int]) -> dict[int, str]:
    """estado_llenado vigente (o "sin_datos") de cada punto crítico pedido."""
    if not ids:
        return {}
    ultimo = reportes_service.ultimo_reporte_por_punto()
    filas = db.execute(
        select(ultimo.c.punto_critico_id, ultimo.c.estado, ultimo.c.creado_en).where(
            ultimo.c.punto_critico_id.in_(ids)
        )
    ).all()
    momento = reportes_service.ahora()
    return {
        punto_id: reportes_service.estado_llenado(estado, creado_en, momento)
        for punto_id, estado, creado_en in filas
    }


def _enriquecer_llenado(db: Session, rutas: list[Ruta]) -> None:
    """Adjunta el último llenado y la prioridad a cada nodo de las paradas.

    Así el conductor ve, dentro de su ruta, qué porcentaje tiene cada
    contenedor sin pedir un endpoint adicional por parada.
    """
    estados = {estado.id: estado for estado in obtener_estados(db)}
    llenado_puntos = _llenado_de_puntos(
        db,
        {p.punto_critico_id for r in rutas for p in r.paradas if p.punto_critico_id},
    )

    for ruta in rutas:
        for parada in ruta.paradas:
            if parada.punto_critico is not None:
                parada.punto_critico.estado_llenado = llenado_puntos.get(
                    parada.punto_critico_id, reportes_service.SIN_DATOS
                )
            nodo = parada.nodo
            if nodo is None:
                continue
            estado = estados.get(nodo.id)
            nodo.llenado = estado.fill_pct if estado else None
            nodo.prioridad = (
                _PRIORIDAD_POR_ESTADO.get(estado.estado) if estado else None
            )


@router.post(
    "",
    response_model=RutaOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("municipalidad"))],
)
def crear_ruta(
    datos: RutaCreate,
    db: Session = Depends(get_db),
):
    camion = db.get(Camion, datos.camion_id)

    if camion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camión no encontrado",
        )

    _validar_conductor(db, datos.conductor_id)

    if datos.fecha_fin < datos.fecha_inicio:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La fecha de fin no puede ser anterior a la fecha de inicio",
        )

    if datos.hora_fin < datos.hora_inicio:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La hora de fin no puede ser anterior a la hora de inicio",
        )

    ordenes = [parada.orden for parada in datos.paradas]

    if len(ordenes) != len(set(ordenes)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El orden de las paradas no puede repetirse",
        )

    for parada in datos.paradas:
        nodo = db.get(Nodo, parada.nodo_id)

        if nodo is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No existe el nodo {parada.nodo_id}",
            )

    nueva_ruta = Ruta(
        fecha_inicio=datos.fecha_inicio,
        fecha_fin=datos.fecha_fin,
        hora_inicio=datos.hora_inicio,
        hora_fin=datos.hora_fin,
        camion_id=datos.camion_id,
        conductor_id=datos.conductor_id,
        estado="Pendiente",
    )

    try:
        db.add(nueva_ruta)
        db.flush()

        for parada in datos.paradas:
            nueva_parada = Parada(
                ruta_id=nueva_ruta.id,
                nodo_id=parada.nodo_id,
                orden=parada.orden,
            )
            db.add(nueva_parada)

        db.commit()
        db.refresh(nueva_ruta)

    except Exception:
        db.rollback()
        raise

    _enriquecer_llenado(db, [nueva_ruta])
    return nueva_ruta


@router.get(
    "/mias",
    response_model=list[RutaOut],
)
def mis_rutas(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(require_roles("municipalidad", "conductor")),
):
    consulta = db.query(Ruta).options(
        joinedload(Ruta.camion),
        selectinload(Ruta.paradas).joinedload(Parada.nodo),
            selectinload(Ruta.paradas).joinedload(Parada.punto_critico),
    )

    if usuario.rol == "conductor":
        consulta = consulta.filter(Ruta.conductor_id == usuario.id)

    rutas = consulta.order_by(Ruta.id).all()
    _enriquecer_llenado(db, rutas)
    return rutas


@router.get(
    "/hoy",
    response_model=list[RutaOut],
    dependencies=[
        Depends(require_roles("municipalidad", "conductor"))
    ],
)
def rutas_del_dia(db: Session = Depends(get_db)):
    hoy = date.today()

    rutas = (
        db.query(Ruta)
        .options(
            joinedload(Ruta.camion),
            selectinload(Ruta.paradas).joinedload(Parada.nodo),
            selectinload(Ruta.paradas).joinedload(Parada.punto_critico),
        )
        .filter(Ruta.fecha_inicio <= hoy, Ruta.fecha_fin >= hoy)
        .order_by(Ruta.id)
        .all()
    )
    _enriquecer_llenado(db, rutas)
    return rutas


@router.post(
    "/generar",
    response_model=RutasTurnoOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("municipalidad"))],
)
def generar_rutas(
    datos: RutaGenerarRequest,
    db: Session = Depends(get_db),
):
    """Genera las rutas de un turno con los puntos críticos reales y la flota real.

    Reemplaza las rutas pendientes de ese turno y fecha; no toca las que están
    en curso o completadas. Ver app/services/generador_rutas.py.
    """
    try:
        resultado = generador_rutas.generar_rutas_turno(
            db,
            turno=datos.turno,
            fecha=datos.fecha or date.today(),
            solo_prioritarios=datos.solo_prioritarios,
            solo_con_reporte_lleno=datos.solo_con_reporte_lleno,
            incluir_reserva=datos.incluir_reserva,
            max_paradas_por_ruta=datos.max_paradas_por_ruta,
        )
    except generador_rutas.SinCamiones as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    except generador_rutas.SinPuntos as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except generador_rutas.ParametroInvalido as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error))

    return RutasTurnoOut(
        turno=resultado.turno,
        fecha=resultado.fecha,
        nro_camiones=resultado.nro_camiones,
        nro_puntos=resultado.nro_puntos,
        max_paradas_por_ruta=resultado.max_paradas_por_ruta,
        metodo_distancia=resultado.metodo_distancia,
        distancia_total_km=round(resultado.distancia_total_km, 3),
        tiempo_total_min=round(sum(r.ruta.tiempo_estimado_min for r in resultado.rutas), 1),
        rutas_reemplazadas=resultado.rutas_reemplazadas,
        camiones_con_ruta_en_curso=resultado.camiones_con_ruta_en_curso,
        parametros=generador_rutas.parametros_usados(resultado.metodo_distancia),
        rutas=[
            RutaGeneradaOut(
                ruta_id=r.ruta.id,
                camion=CamionRutaOut(id=r.camion.id, placa=r.camion.placa),
                conductor_id=r.ruta.conductor_id,
                hora_inicio=r.ruta.hora_inicio,
                hora_fin=r.ruta.hora_fin,
                excede_turno=r.excede_turno,
                distancia_km=r.ruta.distancia_km,
                tiempo_estimado_min=r.ruta.tiempo_estimado_min,
                paradas=[
                    ParadaGeneradaOut(
                        orden=orden,
                        punto_critico_id=p.id,
                        codigo=p.codigo,
                        lat=p.lat,
                        lon=p.lon,
                        direccion=p.direccion,
                    )
                    for orden, p in enumerate(r.paradas, start=1)
                ],
            )
            for r in resultado.rutas
        ],
    )


@router.get(
    "/{ruta_id}",
    response_model=RutaOut,
    dependencies=[
        Depends(require_roles("municipalidad", "conductor"))
    ],
)
def detalle_ruta(ruta_id: int, db: Session = Depends(get_db)):
    ruta = (
        db.query(Ruta)
        .options(
            joinedload(Ruta.camion),
            selectinload(Ruta.paradas).joinedload(Parada.nodo),
            selectinload(Ruta.paradas).joinedload(Parada.punto_critico),
        )
        .filter(Ruta.id == ruta_id)
        .first()
    )

    if ruta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ruta no encontrada",
        )

    _enriquecer_llenado(db, [ruta])
    return ruta


@router.patch(
    "/{ruta_id}",
    response_model=RutaOut,
)
def actualizar_estado_ruta(
    ruta_id: int,
    datos: RutaEstadoUpdate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if usuario.rol not in {"municipalidad", "conductor"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para esta acción",
        )

    ruta = db.get(Ruta, ruta_id)

    if ruta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ruta no encontrada",
        )

    if usuario.rol == "conductor" and ruta.conductor_id != usuario.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta ruta no está asignada a ti",
        )

    ruta.estado = datos.estado
    db.commit()
    db.refresh(ruta)
    _enriquecer_llenado(db, [ruta])
    return ruta


@router.patch(
    "/{ruta_id}/paradas/{parada_id}",
    response_model=ParadaOut,
)
def actualizar_parada(
    ruta_id: int,
    parada_id: int,
    datos: ParadaUpdate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if usuario.rol not in {"municipalidad", "conductor"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para esta acción",
        )

    ruta = db.get(Ruta, ruta_id)

    if ruta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ruta no encontrada",
        )

    if usuario.rol == "conductor" and ruta.conductor_id != usuario.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta ruta no está asignada a ti",
        )

    parada = (
        db.query(Parada)
        .filter(Parada.id == parada_id, Parada.ruta_id == ruta_id)
        .first()
    )

    if parada is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parada no encontrada",
        )

    parada.recolectado = datos.recolectado
    db.commit()
    db.refresh(parada)
    return parada
