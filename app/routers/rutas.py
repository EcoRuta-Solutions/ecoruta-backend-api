from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.deps import get_current_user, require_roles
from app.database import get_db
from app.models.camion import Camion
from app.models.nodo import Nodo
from app.models.ruta import Parada, Ruta
from app.models.usuario import Usuario
from app.routers.panel import obtener_estados
from app.schemas.ruta import (
    ParadaOut,
    ParadaUpdate,
    RutaCreate,
    RutaEstadoUpdate,
    RutaGenerarOut,
    RutaGenerarRequest,
    RutaOut,
)
from app.services.optimizador_service import comparar_optimizadores


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
    )

    if usuario.rol == "conductor":
        consulta = consulta.filter(Ruta.conductor_id == usuario.id)

    return consulta.order_by(Ruta.id).all()


@router.get(
    "/hoy",
    response_model=list[RutaOut],
    dependencies=[
        Depends(require_roles("municipalidad", "conductor"))
    ],
)
def rutas_del_dia(db: Session = Depends(get_db)):
    hoy = date.today()

    return (
        db.query(Ruta)
        .options(
            joinedload(Ruta.camion),
            selectinload(Ruta.paradas).joinedload(Parada.nodo),
        )
        .filter(Ruta.fecha_inicio <= hoy, Ruta.fecha_fin >= hoy)
        .order_by(Ruta.id)
        .all()
    )


TURNOS_HORA_INICIO = {"mañana": 6, "manana": 6, "tarde": 14, "noche": 22}
DURACION_TURNO = timedelta(hours=8)


@router.post(
    "/generar",
    response_model=RutaGenerarOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("municipalidad"))],
)
def generar_ruta(
    datos: RutaGenerarRequest,
    db: Session = Depends(get_db),
):
    camion = db.get(Camion, datos.camion_id)

    if camion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camión no encontrado",
        )

    _validar_conductor(db, datos.conductor_id)

    hora = TURNOS_HORA_INICIO.get(camion.turno.strip().lower())

    if hora is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El camión tiene un turno inválido",
        )

    hora_inicio = datetime.combine(datos.fecha, time(hour=hora))
    hora_fin = hora_inicio + DURACION_TURNO

    existente = (
        db.query(Ruta)
        .filter(
            Ruta.camion_id == datos.camion_id,
            Ruta.fecha_inicio == datos.fecha,
        )
        .first()
    )

    if existente is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El camión ya tiene una ruta para esa fecha",
        )

    criticos = sorted(
        (n for n in obtener_estados(db) if n.estado == "critico"),
        key=lambda n: n.id,
    )

    if not criticos:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay nodos críticos que recolectar",
        )

    if datos.inicio_id is None:
        # Por defecto se inicia en el nodo más lleno.
        indice_inicio = max(
            range(len(criticos)),
            key=lambda i: criticos[i].fill_pct,
        )
    else:
        indices = [
            i for i, n in enumerate(criticos) if n.id == datos.inicio_id
        ]

        if not indices:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El nodo de inicio no es un nodo crítico",
            )

        indice_inicio = indices[0]

    try:
        comparacion = comparar_optimizadores(
            criticos,
            indice_inicio=indice_inicio,
            tiempo_maximo_segundos=3,
        )
    except (ValueError, RuntimeError) as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No se pudo optimizar la ruta: {error}",
        )

    if comparacion["mejor_metodo"] == "clarke_wright_tabu":
        metodo = "clarke_wright_tabu"
        orden = comparacion["ruta_heuristica"]
        distancia = comparacion["distancia_heuristica_km"]
    else:
        metodo = "ortools"
        orden = comparacion["ruta_ortools"]
        distancia = comparacion["distancia_ortools_km"]

    nueva_ruta = Ruta(
        fecha_inicio=datos.fecha,
        fecha_fin=hora_fin.date(),
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        camion_id=datos.camion_id,
        conductor_id=datos.conductor_id,
        estado="Pendiente",
    )

    try:
        db.add(nueva_ruta)
        db.flush()

        for posicion, nodo_id in enumerate(orden, start=1):
            db.add(
                Parada(
                    ruta_id=nueva_ruta.id,
                    nodo_id=nodo_id,
                    orden=posicion,
                )
            )

        db.commit()
        db.refresh(nueva_ruta)

    except Exception:
        db.rollback()
        raise

    return {
        "ruta": nueva_ruta,
        "metodo": metodo,
        "distancia_km": distancia,
        "distancia_ortools_km": comparacion["distancia_ortools_km"],
        "distancia_heuristica_km": comparacion["distancia_heuristica_km"],
    }


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
        )
        .filter(Ruta.id == ruta_id)
        .first()
    )

    if ruta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ruta no encontrada",
        )

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
