"""Sismos de catálogo para la evaluación: únicos, y cuál explica cada decisión de la alerta."""
import math
import pickle
import sys
import time
import urllib.parse

from obspy import UTCDateTime

import config
import sources
from ubicador import TiemposP

TIEMPO_P = TiemposP()
# Residuo admitido (s) entre un disparo y la P teórica del sismo de catálogo. Los disparos
# STA/LTA llegan en promedio ~3 s tarde (calibración del 25-sep al 10-oct)
RES_MIN_S, RES_MAX_S = -10, 15


def clave(ev):
    return f"{ev['source']}:{ev['id']}"


def rhyp(ev, lat, lon):
    return math.hypot(sources.distance_km(lat, lon, ev["lat"], ev["lon"]), ev.get("depth") or 10)


def tiempo_p(ev, lat, lon):
    return float(TIEMPO_P(sources.distance_km(lat, lon, ev["lat"], ev["lon"]), ev.get("depth") or 10))


def eventos(cats, start=None, end=None):
    """Sismos únicos; si dos catálogos traen el mismo, se queda el del SGC, luego USGS."""
    unicos = []
    for name in ("SGC", "USGS", "EMSC"):
        for e in sorted(cats.get(name, []), key=lambda e: e["time"]):
            if e.get("mag") is None or (start and e["time"] < start) or (end and e["time"] > end):
                continue
            if canonico(e, unicos) is None:
                unicos.append(e)
    return sorted(unicos, key=lambda e: e["time"])


def canonico(ev, unicos):
    for u in unicos:
        if abs(ev["time"] - u["time"]) < 20 and \
                sources.distance_km(ev["lat"], ev["lon"], u["lat"], u["lon"]) < 100:
            return u
    return None


def _encajan(estaciones, ev):
    ok, mal = [], []
    for s, v in estaciones.items():
        if v["ratio"] < config.MIN_RATIO or s not in config.STATIONS:
            continue
        r = UTCDateTime(v["onset"]) - ev["time"] - tiempo_p(ev, *config.STATIONS[s][3:5])
        (ok if RES_MIN_S <= r <= RES_MAX_S else mal).append(s)
    return ok, mal


def emparejar(decision, todos):
    """Sismo de catálogo que explica la decisión, o None (falsa detección).

    Cuenta si al menos 2 disparos fuertes encajan con su onda P; con uno solo (HEL sola), si
    encaja, ninguno lo contradice y el sismo está a menos de 300 km de Medellín.
    """
    t = UTCDateTime(decision["primer_disparo"])
    mejor = None
    for ev in todos:
        if not t - 900 <= ev["time"] <= t + 60:
            continue
        ok, mal = _encajan(decision["estaciones"], ev)
        if ok and (mejor is None or len(ok) > len(mejor[1])):
            mejor = (ev, ok, mal)
    if not mejor:
        return None
    ev, ok, mal = mejor
    cerca = sources.distance_km(*config.MEDELLIN, ev["lat"], ev["lon"]) <= 300
    return ev if len(ok) >= 2 or (cerca and not mal) else None


def con_reintentos(f, intentos=4, espera_s=10):
    """Los servicios de catálogo a veces cortan la conexión a mitad de una respuesta grande."""
    for i in range(intentos):
        try:
            return f()
        except Exception as err:
            if i == intentos - 1:
                raise
            print(f"  reintento tras {type(err).__name__}", file=sys.stderr)
            time.sleep(espera_s * (i + 1))


def usgs_historico(inicio, fin, minmag, radio_km):
    """Sismos del USGS alrededor de Medellín, por años (el servicio limita a 20.000)."""
    out = []
    t = inicio
    while t < fin:
        t2 = min(UTCDateTime(t.year + 1, 1, 1), fin)
        q = dict(format="geojson", starttime=str(t)[:19], endtime=str(t2)[:19],
                 latitude=config.MEDELLIN[0], longitude=config.MEDELLIN[1],
                 maxradiuskm=radio_km, minmagnitude=minmag, orderby="time-asc")
        d = con_reintentos(lambda: sources._get_json(
            "https://earthquake.usgs.gov/fdsnws/event/1/query?" + urllib.parse.urlencode(q),
            timeout=120))
        for f in (d or {}).get("features", []):
            p, (lon, lat, depth) = f["properties"], f["geometry"]["coordinates"]
            out.append(sources._event("USGS", f["id"], p["time"] / 1000, lat, lon, depth,
                                      p["mag"], p.get("magType"), p.get("place"),
                                      p.get("status"), p.get("url")))
        print(f"  USGS {t.year}: {len(out)} sismos", file=sys.stderr)
        t = t2
    return out


def cargar(path):
    return pickle.load(open(path, "rb"))
