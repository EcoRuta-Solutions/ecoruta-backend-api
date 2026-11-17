"""Siembra datos de demostración alineados con los mocks del frontend.

Recrea los 8 nodos TRU-001..TRU-008, los 3 camiones y 3 rutas del conductor
que usa el panel municipalidad simulado, para que el usuario conductor vea
información coherente desde la app real.

Seguridad:
- No corre si ya hay datos reales (zonas_ruta o puntos_criticos con filas),
  salvo con --force.
- Solo borra lo marcado como demo: rutas demo (o de camiones demo) y sus
  paradas, camiones demo y las lecturas de los nodos demo. Nodos, vehículos y
  conductores demo se actualizan en su lugar (por código, placa o nombre).
  Nunca borra rutas ni paradas reales.
- Antes aplica scripts/migrar_es_demo.py (columnas es_demo).

Uso:
    python seed_demo.py
    python seed_demo.py --force   # aunque ya haya datos reales cargados
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))

from migrar_es_demo import migrar as migrar_es_demo
from sqlalchemy import inspect, or_, select, text

from app.core.turnos import Turno
from app.database import SessionLocal
from app.models.camion import Camion
from app.models.conductor import Conductor
from app.models.lectura import Lectura
from app.models.nodo import Nodo
from app.models.ruta import Parada, Ruta
from app.models.usuario import Usuario
from app.models.vehiculo import Vehiculo

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

# placa, tipo, capacidad_toneladas, estado
VEHICULOS = [
    ("TCA-241", "Compactador", 8, "operativo"),
    ("TCA-508", "Volquete", 6, "operativo"),
    ("TCA-316", "Compactador", 8, "mantenimiento"),
]

# nombre, telefono, categoria_licencia, estado, vehiculo_idx (1-based), usa_conductor
CONDUCTORES = [
    ("Luis Rodríguez", "944 123 456", "A-IIb", "disponible", 1, True),
    ("María Flores", "955 234 567", "A-IIIa", "en_ruta", 2, False),
    ("José Castillo", "966 345 678", "A-IIb", "descanso", 3, False),
]

# camion_idx (1-based), nodos id (1-based, según orden de NODOS), estado, recolectadas
RUTAS = [
    (1, [1, 2], "Pendiente", []),
    (2, [3, 5], "en_proceso", [3]),
    (3, [6, 7], "Completado", [6, 7]),
]

# Tablas con datos reales: si tienen filas, seed_demo no corre sin --force.
TABLAS_REALES = ("zonas_ruta", "puntos_criticos")


def tablas_reales_con_datos(engine) -> list[str]:
    inspector = inspect(engine)
    ocupadas = []
    with engine.connect() as conexion:
        for tabla in TABLAS_REALES:
            if not inspector.has_table(tabla):
                continue
            cantidad = conexion.scalar(text(f"SELECT count(*) FROM {tabla}"))
            if cantidad:
                ocupadas.append(f"{tabla} ({cantidad} filas)")
    return ocupadas


def borrar_demo(db) -> None:
    """Borra solo lo demo. Las rutas demo son las marcadas o las de un camión demo."""
    rutas_demo = (
        select(Ruta.id)
        .join(Camion, Camion.id == Ruta.camion_id)
        .where(or_(Ruta.es_demo.is_(True), Camion.es_demo.is_(True)))
    )
    db.query(Parada).filter(Parada.ruta_id.in_(rutas_demo)).delete(
        synchronize_session=False
    )
    db.query(Ruta).filter(Ruta.id.in_(rutas_demo)).delete(synchronize_session=False)
    db.query(Camion).filter(Camion.es_demo.is_(True)).delete(
        synchronize_session=False
    )
    nodos_demo = select(Nodo.id).where(Nodo.es_demo.is_(True))
    db.query(Lectura).filter(Lectura.nodo_id.in_(nodos_demo)).delete(
        synchronize_session=False
    )
    db.flush()


def sembrar_nodos(db) -> list:
    """Crea o actualiza por código los nodos demo (no se borran: pueden tener paradas)."""
    existentes = {
        n.codigo: n
        for n in db.query(Nodo).filter(Nodo.codigo.in_([c for c, *_ in NODOS]))
    }
    nodos = []
    for codigo, nombre, lat, lon, fill, tilt in NODOS:
        nodo = existentes.get(codigo) or Nodo(codigo=codigo)
        nodo.nombre = nombre
        nodo.latitud = lat
        nodo.longitud = lon
        nodo.umbral_critico = 80
        nodo.es_demo = True
        db.add(nodo)
        nodos.append((nodo, fill, tilt))
    db.flush()

    for nodo, fill, tilt in nodos:
        if fill is not None:
            db.add(Lectura(nodo_id=nodo.id, fill_pct=fill, tilt_alert=tilt))
    return nodos


def sembrar_vehiculos_y_conductores(db, conductor) -> None:
    """Upsert por placa (vehículos) y por nombre (conductores); no borra nada.

    Estas tablas no tienen es_demo: quedan fuera de scripts/limpiar_datos_demo.py.
    """
    vehiculos = []
    for placa, tipo, capacidad, estado in VEHICULOS:
        vehiculo = db.query(Vehiculo).filter(Vehiculo.placa == placa).first()
        if vehiculo is None:
            vehiculo = Vehiculo(placa=placa)
            db.add(vehiculo)
        vehiculo.tipo = tipo
        vehiculo.capacidad_toneladas = capacidad
        vehiculo.estado = estado
        vehiculos.append(vehiculo)
    db.flush()

    for nombre, telefono, licencia, estado, vehiculo_idx, usa in CONDUCTORES:
        registro = db.query(Conductor).filter(Conductor.nombre == nombre).first()
        if registro is None:
            registro = Conductor(nombre=nombre)
            db.add(registro)
        registro.usuario_id = conductor.id if usa else None
        registro.telefono = telefono
        registro.categoria_licencia = licencia
        registro.estado = estado
        registro.vehiculo_id = vehiculos[vehiculo_idx - 1].id
    db.flush()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Siembra los datos demo.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Correr aunque ya haya zonas_ruta o puntos_criticos cargados",
    )
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        engine = db.get_bind()

        ocupadas = tablas_reales_con_datos(engine)
        if ocupadas and not args.force:
            raise SystemExit(
                "seed_demo.py no se ejecuta: ya hay datos reales en "
                + ", ".join(ocupadas)
                + ". Usa --force para sembrar la demo junto a ellos "
                "(solo reemplaza lo marcado como demo)."
            )

        migrar_es_demo(engine)

        conductor = (
            db.query(Usuario)
            .filter(Usuario.rol == "conductor")
            .order_by(Usuario.id)
            .first()
        )
        if conductor is None:
            raise SystemExit("No hay ningún usuario con rol 'conductor'.")

        try:
            borrar_demo(db)
            nodos = sembrar_nodos(db)

            camiones = []
            for placa, capacidad, turno in CAMIONES:
                camion = Camion(
                    placa=placa,
                    capacidad=capacidad,
                    turno=turno,
                    estado="operativo",
                    es_demo=True,
                )
                db.add(camion)
                camiones.append(camion)
            db.flush()

            sembrar_vehiculos_y_conductores(db, conductor)

            hoy = date.today()
            turno = Turno.manana
            for camion_idx, nodos_ids, estado, recolectadas in RUTAS:
                ruta = Ruta(
                    fecha_inicio=hoy,
                    fecha_fin=hoy,
                    hora_inicio=datetime.combine(hoy, turno.inicio),
                    hora_fin=datetime.combine(hoy, turno.fin),
                    camion_id=camiones[camion_idx - 1].id,
                    conductor_id=conductor.id,
                    estado=estado,
                    es_demo=True,
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
        except Exception:
            db.rollback()
            raise

        print(f"Nodos demo: {len(NODOS)}")
        print(f"Camiones demo: {len(CAMIONES)}")
        print(f"Vehículos demo: {len(VEHICULOS)}")
        print(f"Conductores demo: {len(CONDUCTORES)}")
        print(f"Rutas demo para el conductor '{conductor.nombre}' (id {conductor.id}):")
        for camion_idx, nodos_ids, estado, _ in RUTAS:
            print(
                f"  - camión {CAMIONES[camion_idx - 1][0]} · {estado} · "
                f"{len(nodos_ids)} paradas"
            )


if __name__ == "__main__":
    main()
