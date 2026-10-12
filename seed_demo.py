"""Siembra datos de demostración alineados con los mocks del frontend.

Recrea los 8 nodos TRU-001..TRU-008, los 3 camiones y 3 rutas del conductor
que usa el panel municipalidad simulado, para que el usuario conductor vea
información coherente desde la app real.
"""

from datetime import date, datetime, time

from sqlalchemy import text

from app.database import SessionLocal
from app.models.camion import Camion
from app.models.lectura import Lectura
from app.models.nodo import Nodo
from app.models.ruta import Parada, Ruta
from app.models.usuario import Usuario

NODOS = [
    # codigo, nombre, lat, lon, fill_pct (None = sin lecturas), tilt
    ("TRU-001", "Mercado Central", -8.1116, -79.0288, 94, False),
    ("TRU-002", "Av. España", -8.1099, -79.0310, 86, True),
    ("TRU-003", "Plaza de Armas", -8.1110, -79.0279, 77, False),
    ("TRU-004", "Urb. Primavera", -8.1048, -79.0322, 70, False),
    ("TRU-005", "Av. Larco", -8.1232, -79.0358, 45, False),
    ("TRU-006", "Parque César Vallejo", -8.1162, -79.0209, 39, False),
    ("TRU-007", "Urb. El Recreo", -8.1181, -79.0271, 18, False),
    ("TRU-008", "Av. América Oeste", -8.1080, -79.0390, None, False),
]

CAMIONES = [
    ("TCA-241", 8000, "Mañana"),
    ("TCA-508", 6000, "Tarde"),
    ("TCA-316", 8000, "Noche"),
]

# camion_idx (1-based), nodos id (1-based, según orden de NODOS), estado, recolectadas
RUTAS = [
    (1, [1, 2], "Pendiente", []),
    (2, [3, 5], "en_proceso", [3]),
    (3, [6, 7], "Completado", [6, 7]),
]


def main() -> None:
    db = SessionLocal()
    try:
        db.execute(
            text(
                "TRUNCATE TABLE paradas, rutas, lecturas, nodos, camiones "
                "RESTART IDENTITY CASCADE"
            )
        )
        db.commit()

        nodos = []
        for codigo, nombre, lat, lon, fill, tilt in NODOS:
            nodo = Nodo(
                codigo=codigo,
                nombre=nombre,
                latitud=lat,
                longitud=lon,
                umbral_critico=80,
            )
            db.add(nodo)
            nodos.append((nodo, fill, tilt))

        db.flush()

        for nodo, fill, tilt in nodos:
            if fill is not None:
                db.add(
                    Lectura(nodo_id=nodo.id, fill_pct=fill, tilt_alert=tilt)
                )

        camiones = []
        for placa, capacidad, turno in CAMIONES:
            camion = Camion(placa=placa, capacidad=capacidad, turno=turno)
            db.add(camion)
            camiones.append(camion)

        db.flush()

        conductor = (
            db.query(Usuario).filter(Usuario.rol == "conductor").first()
        )
        if conductor is None:
            raise SystemExit("No hay ningún usuario con rol 'conductor'.")

        hoy = date.today()
        for camion_idx, nodos_ids, estado, recolectadas in RUTAS:
            ruta = Ruta(
                fecha_inicio=hoy,
                fecha_fin=hoy,
                hora_inicio=datetime.combine(hoy, time(hour=6)),
                hora_fin=datetime.combine(hoy, time(hour=14)),
                camion_id=camiones[camion_idx - 1].id,
                conductor_id=conductor.id,
                estado=estado,
            )
            db.add(ruta)
            db.flush()

            for orden, nodo_id in enumerate(nodos_ids, start=1):
                db.add(
                    Parada(
                        ruta_id=ruta.id,
                        nodo_id=nodos[nodo_id - 1][0].id,
                        orden=orden,
                        recolectado=nodo_id in recolectadas,
                    )
                )

        db.commit()

        print(f"Nodos creados: {len(NODOS)}")
        print(f"Camiones creados: {len(CAMIONES)}")
        print(f"Rutas creadas para el conductor '{conductor.nombre}' (id {conductor.id}):")
        for camion_idx, nodos_ids, estado, _ in RUTAS:
            print(f"  - camión {CAMIONES[camion_idx - 1][0]} · {estado} · {len(nodos_ids)} paradas")
    finally:
        db.close()


if __name__ == "__main__":
    main()
