"""Alertas de contenedor lleno: se crean una vez por episodio y se resuelven solas."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.alerta import TIPO_CONTENEDOR_LLENO, Alerta
from app.models.punto_critico import PuntoCritico

MOTIVO_NIVEL_BAJO = "nivel_bajo"
MOTIVO_RECOLECTADO = "recolectado"


def activa_de(db: Session, punto_id: int, tipo: str = TIPO_CONTENEDOR_LLENO) -> Alerta | None:
    return (
        db.query(Alerta)
        .filter(Alerta.punto_critico_id == punto_id, Alerta.tipo == tipo, Alerta.activa.is_(True))
        .first()
    )


def mensaje_contenedor_lleno(codigo: str, nivel_pct: float) -> str:
    return f"Contenedor lleno: {codigo} ({nivel_pct:.0f}%)"


def abrir_si_no_hay(db: Session, punto: PuntoCritico, nivel_pct: float) -> Alerta | None:
    """Crea la alerta si el punto no tiene una activa. Devuelve la nueva o None."""
    if activa_de(db, punto.id) is not None:
        return None  # ya avisada en este episodio: no se repite en cada lectura
    alerta = Alerta(
        tipo=TIPO_CONTENEDOR_LLENO,
        punto_critico_id=punto.id,
        mensaje=mensaje_contenedor_lleno(punto.codigo_unico, nivel_pct),
        nivel_pct=nivel_pct,
        activa=True,
    )
    db.add(alerta)
    db.flush()
    return alerta


def resolver(db: Session, punto_id: int, motivo: str) -> int:
    """Cierra las alertas activas del punto. No hace commit. Devuelve cuántas cerró."""
    alertas = (
        db.query(Alerta)
        .filter(Alerta.punto_critico_id == punto_id, Alerta.activa.is_(True))
        .all()
    )
    for alerta in alertas:
        alerta.activa = False
        alerta.resuelta_en = datetime.now(timezone.utc)
        alerta.motivo_resolucion = motivo
    return len(alertas)
