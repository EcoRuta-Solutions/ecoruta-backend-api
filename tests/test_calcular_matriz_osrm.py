"""scripts/calcular_matriz_distancias.py con OSRM simulado (no sale a la red)."""

import io
import json
import urllib.error

import pytest

from app import config
from app.services import distancias_service as ds
from conftest import matriz_osrm as m

URL = "http://osrm.prueba"


def puntos(n):
    return [ds.Punto(f"P-{i}", -8.10 + i * 0.001, -79.03 - i * 0.001) for i in range(n)]


class OsrmFalso:
    """Responde distancia 10*i + j; puede fallar las primeras veces en ciertos bloques."""

    def __init__(self, lista, fallos=None, nulos=()):
        self.lista = lista
        self.fallos = dict(fallos or {})  # (primer origen, primer destino) -> fallos pendientes
        self.nulos = set(nulos)
        self.llamadas = []

    def __call__(self, url, origenes, destinos):
        clave = (self.lista.index(origenes[0]), self.lista.index(destinos[0]))
        self.llamadas.append((clave, len(origenes), len(destinos)))
        coordenadas = len(origenes) + (0 if origenes == destinos else len(destinos))
        if coordenadas < 2:
            raise m.ErrorOsrm('HTTP 400: {"message":"Number of coordinates needs to be at least two."}')
        if self.fallos.get(clave, 0) > 0:
            self.fallos[clave] -= 1
            raise m.ErrorOsrm('HTTP 400: {"code":"InvalidQuery"}')
        filas = []
        for o in origenes:
            i = self.lista.index(o)
            filas.append([
                None if (i, self.lista.index(d)) in self.nulos else float(10 * i + self.lista.index(d))
                for d in destinos
            ])
        return filas


def calcular(lista, osrm, **kwargs):
    esperas = []
    resultado = m.calcular(
        lista, URL, consultar=osrm, pausa=0, espera_base=1, dormir=esperas.append, **kwargs
    )
    return resultado, esperas


# --- Bloques -----------------------------------------------------------------------------


def test_bloques_equilibrados_sin_bloque_de_un_punto():
    tamanos = [len(b) for b in m.dividir_en_bloques(151, 25)]

    assert tamanos == [22, 22, 22, 22, 21, 21, 21]  # antes: 25×6 + 1 (el que fallaba)
    assert sum(tamanos) == 151 and max(tamanos) <= 25


def test_ultimo_bloque_irregular_completa_la_matriz():
    lista = puntos(5)  # bloque 2 -> tamaños [2, 2, 1]
    osrm = OsrmFalso(lista)

    resultado, _ = calcular(lista, osrm, bloque=2)

    assert [len(b) for b in m.dividir_en_bloques(5, 2)] == [2, 2, 1]
    # El bloque diagonal de 1 punto no se pide (OSRM exige ≥ 2 coordenadas).
    assert resultado.peticiones == 8
    assert all(o + (0 if c[0] == c[1] else d) >= 2 for c, o, d in osrm.llamadas)
    assert resultado.distancias_m[4][1] == 41.0 and resultado.distancias_m[1][4] == 14.0
    assert all(resultado.distancias_m[i][i] == 0.0 for i in range(5))
    m.validar(resultado.distancias_m, 5)


def test_un_solo_punto_no_hace_peticiones():
    resultado, _ = calcular(puntos(1), OsrmFalso(puntos(1)), bloque=25)

    assert resultado.peticiones == 0
    assert resultado.distancias_m == [[0.0]]


# --- Reintentos y reanudación ----------------------------------------------------------


def test_400_se_recupera_tras_un_reintento():
    lista = puntos(5)
    osrm = OsrmFalso(lista, fallos={(4, 0): 1})  # el último bloque falla una vez

    resultado, esperas = calcular(lista, osrm, bloque=2)

    assert resultado.distancias_m[4][0] == 40.0
    assert esperas == [1]  # una espera antes del reintento
    assert [c for c, *_ in osrm.llamadas].count((4, 0)) == 2


def test_espera_creciente_y_error_si_se_agotan_los_intentos(tmp_path):
    lista = puntos(5)
    osrm = OsrmFalso(lista, fallos={(4, 0): 99})
    parcial = tmp_path / "matriz.parcial.json"

    with pytest.raises(m.ErrorOsrm, match="falló tras 3 intentos"):
        calcular(lista, osrm, bloque=2, intentos=3, archivo_parcial=parcial)

    assert parcial.is_file()  # el avance quedó guardado
    assert len(json.loads(parcial.read_text(encoding="utf-8"))["hechos"]) == 6


def test_reanuda_desde_el_archivo_parcial(tmp_path):
    lista = puntos(5)
    parcial = tmp_path / "matriz.parcial.json"
    with pytest.raises(m.ErrorOsrm):
        calcular(lista, OsrmFalso(lista, fallos={(4, 0): 99}), bloque=2, intentos=1, archivo_parcial=parcial)

    osrm = OsrmFalso(lista)
    resultado, _ = calcular(lista, osrm, bloque=2, archivo_parcial=parcial)

    assert resultado.bloques_reanudados == 6
    assert [c for c, *_ in osrm.llamadas] == [(4, 0), (4, 2)]  # solo lo que faltaba
    completo, _ = calcular(lista, OsrmFalso(lista), bloque=2)
    assert resultado.distancias_m == completo.distancias_m


def test_parcial_de_otros_puntos_se_ignora(tmp_path):
    parcial = tmp_path / "matriz.parcial.json"
    with pytest.raises(m.ErrorOsrm):
        calcular(puntos(5), OsrmFalso(puntos(5), fallos={(4, 0): 99}), bloque=2, intentos=1,
                 archivo_parcial=parcial)

    otros = puntos(6)
    resultado, _ = calcular(otros, OsrmFalso(otros), bloque=2, archivo_parcial=parcial)

    assert resultado.bloques_reanudados == 0


# --- Pares sin ruta y validación -------------------------------------------------------


def test_pares_sin_ruta_quedan_aproximados_e_informados():
    lista = puntos(4)
    osrm = OsrmFalso(lista, nulos={(0, 3), (2, 1)})

    resultado, _ = calcular(lista, osrm, bloque=2)

    assert sorted(resultado.pares_aproximados) == [(0, 3), (2, 1)]
    a, b = lista[0], lista[3]
    esperado = ds.haversine_km(a.lat, a.lon, b.lat, b.lon) * config.OPTIMIZADOR_FACTOR_CIRCUITO * 1000
    assert resultado.distancias_m[0][3] == pytest.approx(esperado)
    m.validar(resultado.distancias_m, 4)


@pytest.mark.parametrize(
    "matriz",
    [
        [[0, 1], [1, 0], [1, 1]],  # no es N×N
        [[0, None], [1, 0]],  # nulo
        [[5, 1], [1, 0]],  # diagonal distinta de 0
        [[0, -1], [1, 0]],  # negativa
    ],
)
def test_matriz_incompleta_no_escribe_el_archivo(tmp_path, matriz):
    ruta = tmp_path / "matriz.json"

    with pytest.raises(m.MatrizInvalida):
        m.guardar(puntos(2), matriz, ruta, URL)

    assert not ruta.exists()


def test_guarda_pares_aproximados_y_se_lee_como_osrm(tmp_path):
    lista = puntos(3)
    ruta = tmp_path / "matriz.json"
    matriz = [[0, 100, 200], [100, 0, 300], [200, 300, 0]]

    m.guardar(lista, matriz, ruta, URL, pares_aproximados=[(0, 2)])

    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos["pares_aproximados"] == [["P-0", "P-2"]]
    assert ds.matriz_para_puntos(lista, cache=ds.cargar_cache(ruta)).metodo == "osrm"


# --- Petición HTTP ---------------------------------------------------------------------


def test_http_400_conserva_el_mensaje_del_servidor(monkeypatch):
    def urlopen(peticion, timeout):
        raise urllib.error.HTTPError(
            peticion.full_url, 400, "Bad Request", {},
            io.BytesIO(b'{"message":"Number of coordinates needs to be at least two.","code":"InvalidOptions"}'),
        )

    monkeypatch.setattr(m.urllib.request, "urlopen", urlopen)

    with pytest.raises(m.ErrorOsrm, match="HTTP 400.*at least two"):
        m.consultar_bloque(URL, puntos(2), puntos(2))


def test_un_bloque_de_una_coordenada_no_se_envia(monkeypatch):
    monkeypatch.setattr(m.urllib.request, "urlopen", lambda *a, **k: pytest.fail("no debía pedir"))
    uno = puntos(1)

    with pytest.raises(m.ErrorOsrm, match="al menos 2 coordenadas"):
        m.consultar_bloque(URL, uno, uno)
