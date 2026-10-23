"""Lo que de verdad tembló en cada sitio: intensidad y hora de cada cruce de umbral.

Los sitios son las estaciones de la red (config.STATIONS); Medellín es HEL (a 8 km). Para
cada sismo se baja la señal de las dos componentes horizontales (fuentes.py: SGC y
EarthScope), se quita la respuesta del sensor y, como Meier (2017), se toma la suma
vectorial de las horizontales. La MMI sale de la velocidad máxima (Worden et al., 2012, como ShakeMap 4) y se anota el
primer instante en que cruza cada nivel, de 1,5 a 7 cada 0,5 (para los umbrales y la
tolerancia de ±0,5).

Los sensores son de banda ancha: con sacudidas fuertes (MMI ≳ 6) pueden saturarse; se marca.
"""
import json
import os
import sys

import numpy as np
from obspy import UTCDateTime

import config

from . import intensidad
from .catalogo import clave, tiempo_p
from .fuentes import ClienteMixto

MEDELLIN = config.LOCAL_STATION
NIVELES = [round(x, 1) for x in np.arange(1.5, 7.01, 0.5)]


def sitios():
    """{estación: (red, ubicación, canal vertical, lat, lon)}."""
    return dict(config.STATIONS)


def fin_ventana(ev):
    """Hasta cuándo mirar: la S más lejana (≈1,8 veces la P) más 150 s de ondas superficiales."""
    tp = max(tiempo_p(ev, *v[3:5]) for v in sitios().values())
    return ev["time"] + min(1.8 * tp + 150, 900)


def _medir_sitio(trs, inv, ev, lat, lon):
    horiz = [tr for tr in trs if tr.stats.channel[-1] in "NE12"]
    if len(horiz) < 2:
        raise ValueError("faltan componentes horizontales")
    horiz = horiz[:2]
    saturada = any(np.abs(tr.data).max() > 0.9 * 2 ** 23 for tr in horiz)
    ini = max(tr.stats.starttime for tr in horiz)
    fin = min(tr.stats.endtime for tr in horiz)
    curvas = {}
    for salida in ("ACC", "VEL"):
        comp = []
        for tr in horiz:
            tr = tr.copy()
            tr.detrend("demean")
            tr.taper(0.05)
            tr.remove_response(inventory=inv, output=salida, pre_filt=(0.05, 0.1, 35, 45),
                               water_level=60)
            tr.trim(ini, fin)
            comp.append(tr.data)
        n = min(len(c) for c in comp)
        # Suma vectorial de las dos horizontales, en cm/s² o cm/s
        curvas[salida] = np.hypot(comp[0][:n], comp[1][:n]) * 100
    n = min(len(c) for c in curvas.values())
    t = (ini - ev["time"]) + np.arange(n) / horiz[0].stats.sampling_rate
    tp = tiempo_p(ev, lat, lon)
    llega = t >= tp - 5
    antes = (t > t[0] + 10) & ~llega  # sin el borde del filtro
    if not antes.any():
        raise ValueError("no hay señal antes de la P")
    ruido = float(intensidad.mmi_observada(curvas["ACC"][antes].max(), curvas["VEL"][antes].max()))
    pga = np.maximum.accumulate(np.where(llega, curvas["ACC"][:n], 0))
    pgv = np.maximum.accumulate(np.where(llega, curvas["VEL"][:n], 0))
    mmi = intensidad.mmi_observada(pga, pgv)
    cruces = {}
    for u in NIVELES:
        i = int(np.argmax(mmi >= u))
        cruces[f"{u:.1f}"] = str(ev["time"] + float(t[i])) if mmi[i] >= u and ruido < u else None
    return {"mmi": round(float(mmi[-1]), 2), "pga_cms2": round(float(pga[-1]), 4),
            "pgv_cms": round(float(pgv[-1]), 5), "ruido_mmi": round(ruido, 2),
            "saturada": bool(saturada), "cruces": cruces}


def observar(ev, client, inv):
    """{sitio: medida o {"error": ...}} para un sismo."""
    t0 = ev["time"]
    bulk = [(net, s, loc or "--", cha[:2] + "?", t0 - 90, fin_ventana(ev))
            for s, (net, loc, cha, *_) in sitios().items()]
    st = client.get_waveforms_bulk(bulk)
    st.merge(method=1, fill_value=0)
    out = {}
    for s, (net, loc, cha, lat, lon) in sitios().items():
        trs = st.select(station=s, channel=cha[:2] + "?")
        try:
            out[s] = _medir_sitio(trs, inv, ev, lat, lon)
        except Exception as err:
            out[s] = {"error": f"{type(err).__name__}: {err}"[:200]}
    return out


def inventario(client):
    inv = None
    for s, (net, loc, cha, *_) in sitios().items():
        try:
            i = client.get_stations(network=net, station=s, location=loc or "--",
                                    channel=cha[:2] + "?", level="response")
            inv = i if inv is None else inv + i
        except Exception as err:
            print(f"  sin respuesta para {s}: {err}", file=sys.stderr)
    return inv


def medir(evs, path, client=None):
    """Mide (o lee de la caché, un JSON {sismo: {sitio: medida}}) la intensidad de cada sismo."""
    cache = json.load(open(path, encoding="utf-8")) if path and os.path.exists(path) else {}
    faltan = [e for e in evs if clave(e) not in cache]
    if faltan:
        client = client or ClienteMixto()
        inv = inventario(client)
        for i, e in enumerate(faltan, 1):
            try:
                cache[clave(e)] = observar(e, client, inv)
            except Exception as err:
                cache[clave(e)] = {"error": f"{type(err).__name__}: {err}"[:200]}
            if i % 10 == 0 or i == len(faltan):
                print(f"  intensidad observada: {i}/{len(faltan)}", file=sys.stderr)
                if path:
                    json.dump(cache, open(path, "w", encoding="utf-8"))
    return cache


def de_sitio(obs, ev, sitio):
    """Medida de un sitio para un sismo, o None si no hay (sin datos o con error)."""
    o = (obs.get(clave(ev)) or {}).get(sitio)
    return o if o and "error" not in o else None


def hora(cruce):
    return UTCDateTime(cruce) if cruce else None
