from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.connection_manager import connection_manager
from app.core.deps import verify_device_key
from app.database import get_db
from app.schemas.sensor import AlertaBreve, LecturaSensorIn, LecturaSensorOut
from app.services import sensor_service

router = APIRouter(prefix="/sensores", tags=["Sensores"])


@router.post(
    "/lecturas",
    response_model=LecturaSensorOut,
    status_code=201,
    dependencies=[Depends(verify_device_key)],
)
def recibir_lectura(
    datos: LecturaSensorIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Lectura de un sensor de contenedor (ESP32). Exige el encabezado X-API-Key."""
    try:
        resultado = sensor_service.registrar_lectura(db, datos.codigo, datos.nivel_pct)
    except sensor_service.NodoNoEncontrado as error:
        raise HTTPException(status_code=404, detail=str(error))

    for evento in resultado.eventos:
        background_tasks.add_task(connection_manager.broadcast, evento)

    alerta = resultado.alerta_nueva
    return LecturaSensorOut(
        lectura_id=resultado.lectura.id,
        codigo=resultado.nodo.codigo,
        nivel_pct=datos.nivel_pct,
        estado_llenado=resultado.estado.value,
        punto_codigo=resultado.punto.codigo_unico if resultado.punto else None,
        vigente_hasta=resultado.vigente_hasta,
        alerta_creada=AlertaBreve(id=alerta.id, mensaje=alerta.mensaje) if alerta else None,
        alertas_resueltas=resultado.alertas_resueltas,
    )
