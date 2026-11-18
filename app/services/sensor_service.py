"""Ingesta de lecturas del sensor de un contenedor (p. ej. ESP32 + HC-SR04 en PROTO-UTP).

Cada lectura:
1. se guarda en `lecturas` (historial del nodo);
2. si el nodo está vinculado a un punto crítico (puntos_criticos.nodo_id), se
   guarda también como reporte de llenado con origen "sensor" (sin usuario,
   nunca demo, vigencia SENSOR_VIGENCIA_MIN), así el punto muestra su estado en
   el mapa y entra en "solo puntos llenos";
3. abre UNA alerta al pasar a lleno/desbordado y la resuelve al bajar de lleno.
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app import config
from app.models.alerta import Alerta
from app.models.lectura import Lectura
from app.models.nodo import Nodo
from app.models.punto_critico import PuntoCritico
from app.models.reporte_campo import EstadoReporte, OrigenReporte, ReporteCampo
from app.services import alertas_service, reportes_service

ESTADOS_LLENOS = {EstadoReporte.lleno, EstadoReporte.desbordado}


class NodoNoEncontrado(Exception):
    pass


@dataclass
class ResultadoLectura:
    nodo: Nodo
    lectura: Lectura
    estado: EstadoReporte
    punto: PuntoCritico | None = None
    reporte: ReporteCampo | None = None
    alerta_nueva: Alerta | None = None
    alertas_resueltas: int = 0
    eventos: list[dict] = field(default_factory=list)

    @property
    def vigente_hasta(self) -> datetime | None:
        if self.reporte is None:
            return None
        return self.reporte.creado_en + reportes_service.vigencia(OrigenReporte.sensor.value)


def registrar_lectura(db: Session, codigo: str, nivel_pct: float) -> ResultadoLectura:
    nodo = db.query(Nodo).filter(Nodo.codigo == codigo.strip()).first()
    if nodo is None:
        raise NodoNoEncontrado("No existe un nodo con ese código")

    estado = reportes_service.estado_por_nivel(nivel_pct)
    lectura = Lectura(nodo_id=nodo.id, fill_pct=nivel_pct, tilt_alert=False)
    db.add(lectura)
    resultado = ResultadoLectura(nodo=nodo, lectura=lectura, estado=estado)

    punto = db.query(PuntoCritico).filter(PuntoCritico.nodo_id == nodo.id).first()
    if punto is not None:
        resultado.punto = punto
        resultado.reporte = ReporteCampo(
            punto_critico_id=punto.id,
            usuario_id=None,
            origen=OrigenReporte.sensor.value,
            nivel_pct=nivel_pct,
            estado=estado,
            es_demo=False,  # un sensor no es una cuenta demo
        )
        db.add(resultado.reporte)

        if estado in ESTADOS_LLENOS:
            resultado.alerta_nueva = alertas_service.abrir_si_no_hay(db, punto, nivel_pct)
        elif nivel_pct < config.SENSOR_NIVEL_LLENO:
            resultado.alertas_resueltas = alertas_service.resolver(
                db, punto.id, alertas_service.MOTIVO_NIVEL_BAJO
            )

    db.commit()
    db.refresh(lectura)
    if resultado.reporte is not None:
        db.refresh(resultado.reporte)

    evento = {
        "tipo": "sensor_lectura",
        "codigo": nodo.codigo,
        "punto": punto.codigo_unico if punto else None,
        "nivel_pct": nivel_pct,
        "estado_llenado": estado.value,
        "timestamp": lectura.timestamp.isoformat(),
    }
    resultado.eventos.append(evento)
    if resultado.alerta_nueva is not None:
        resultado.eventos.append(
            {
                "tipo": "alerta_nueva",
                "alerta_id": resultado.alerta_nueva.id,
                "punto": punto.codigo_unico,
                "mensaje": resultado.alerta_nueva.mensaje,
                "nivel_pct": nivel_pct,
            }
        )
    if resultado.alertas_resueltas:
        resultado.eventos.append(
            {"tipo": "alerta_resuelta", "punto": punto.codigo_unico, "motivo": "nivel_bajo"}
        )
    return resultado
