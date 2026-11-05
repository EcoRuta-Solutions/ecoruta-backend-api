"""Turnos de recolección de SEGAT (Municipalidad de Trujillo).

- mañana: 05:00–13:00
- tarde:  13:00–21:00
- noche:  21:00–05:00 (cruza la medianoche)

El inicio es inclusivo y el fin exclusivo, así cada hora del día cae en un
único turno: las 13:00 ya son tarde y las 05:00 ya son mañana.
"""

import enum
import unicodedata
from datetime import time


class Turno(str, enum.Enum):
    manana = "manana"
    tarde = "tarde"
    noche = "noche"

    @property
    def inicio(self) -> time:
        return HORARIOS[self][0]

    @property
    def fin(self) -> time:
        return HORARIOS[self][1]

    @property
    def cruza_medianoche(self) -> bool:
        return self.fin <= self.inicio

    def incluye(self, hora: time) -> bool:
        """Indica si `hora` cae dentro del turno (inicio inclusivo, fin exclusivo)."""
        hora = hora.replace(tzinfo=None)
        if self.cruza_medianoche:
            return hora >= self.inicio or hora < self.fin
        return self.inicio <= hora < self.fin


HORARIOS: dict[Turno, tuple[time, time]] = {
    Turno.manana: (time(5, 0), time(13, 0)),
    Turno.tarde: (time(13, 0), time(21, 0)),
    Turno.noche: (time(21, 0), time(5, 0)),
}


def hora_en_turno(hora: time, turno: Turno) -> bool:
    return turno.incluye(hora)


def turno_de_hora(hora: time) -> Turno:
    """Devuelve el turno al que pertenece una hora del día."""
    return next(turno for turno in Turno if turno.incluye(hora))


def normalizar_turno(valor: str | None) -> Turno | None:
    """Convierte un texto de turno a `Turno`.

    Acepta el formato nuevo (`manana`) y el de los camiones demo (`Mañana`),
    sin importar mayúsculas, tildes ni espacios. Devuelve None si no lo reconoce.
    """
    if not valor:
        return None
    sin_tildes = unicodedata.normalize("NFKD", valor.strip().lower())
    texto = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    try:
        return Turno(texto)
    except ValueError:
        return None
