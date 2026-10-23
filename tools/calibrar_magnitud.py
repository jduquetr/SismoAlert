"""Calibra la magnitud preliminar con la amplitud máxima medida en nuestras estaciones.

El sistema de Japón estima la magnitud de cada estación con una fórmula de la amplitud
máxima y la distancia, y toma la mediana de las 5 más cercanas (Tamaribuchi et al., 2014;
Kodera et al., 2021). Sus coeficientes son para la red japonesa; aquí se ajustan con
sismos de catálogo registrados por nuestras 11 estaciones:

    M = a·log10(A) + b·log10(R) + c + corrección de la estación

A: amplitud máxima de la componente vertical en los primeros 5 o 30 s desde la onda P
(config.MAGNITUD_VENTANAS_S), medida igual que en vivo (magnitud.medir): desplazamiento
(m) en 0,2-5 Hz y velocidad (m/s) en la banda del detector; R: distancia hipocentral (km).
Cada tipo de señal y cada ventana tiene sus coeficientes.

1. Pide al USGS los sismos de los últimos DIAS días (M>=3) dentro de REGION, y al SGC los
   pequeños (M>=2) cerca de nuestras estaciones, que el USGS no tiene.
2. Baja de EarthScope la señal de cada estación alrededor de la onda P teórica (IASP91)
   y la sensibilidad de cada sensor. Todo queda en la carpeta --cache para repetir el
   ajuste sin volver a bajar nada.
3. Ajusta a, b, c por mínimos cuadrados (cada medio grado de magnitud con el mismo peso)
   con las medidas que superan 3 veces el ruido, y
   la corrección de cada estación como la mediana de sus residuos.
4. Valida: ajusta con el 75 % más antiguo y mide el error de la magnitud del sismo, como
   la calcula el sistema, en el 25 % más reciente.

Escribe magnitud.json (lo usa magnitud.py). Uso:
    python tools/calibrar_magnitud.py --cache CARPETA [--dias 365] [--solo-ajustar]
"""
import argparse
import collections
import csv
import io
import json
import os
import random
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from obspy import UTCDateTime, read
from obspy.clients.fdsn import Client

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config  # noqa: E402
import magnitud  # noqa: E402
import sources  # noqa: E402
from ubicador import TiemposP, _distance_km  # noqa: E402

USGS = ("https://earthquake.usgs.gov/fdsnws/event/1/query?format=csv&starttime={t0}"
        "&endtime={t1}&minlatitude={minlat}&maxlatitude={maxlat}&minlongitude={minlon}"
        "&maxlongitude={maxlon}&minmagnitude=3&orderby=time-asc")
MAX_DIST_KM = 1500
ANTES_S, DESPUES_S = 40, 40  # ventana que se baja alrededor de la P
SNR_MIN = 3
SGC_POR_BIN = 400


def eventos_usgs(dias):
    t1 = UTCDateTime()
    url = USGS.format(t0=(t1 - dias * 86400).date, t1=t1.date, **config.REGION)
    with urllib.request.urlopen(url, timeout=120) as r:
        rows = list(csv.DictReader(io.StringIO(r.read().decode())))
    return [{"id": r["id"], "time": r["time"], "lat": float(r["latitude"]),
             "lon": float(r["longitude"]), "depth": float(r["depth"] or 10),
             "mag": float(r["mag"]), "magType": r["magType"], "fuente": "USGS"} for r in rows]


def eventos_sgc(dias):
    """Sismos pequeños del SGC que nuestras estaciones alcanzan a registrar: M>=2 a menos de
    100·(M-1,5) km de alguna (M2 a 50 km, M3 a 150 km), como mucho SGC_POR_BIN por cada
    medio grado de magnitud (al azar) para no bajar decenas de miles."""
    t1 = UTCDateTime()
    t = t1 - dias * 86400
    evs = []
    while t < t1:
        try:
            evs += sources.sgc_biweekly(t, min(t + 10 * 86400, t1))
        except Exception as e:
            print(f"SGC {t.date}: {e}")
        t += 10 * 86400
    out = []
    for e in evs:
        m = e.get("mag")
        if m is None or m < 2:
            continue
        near = min(_distance_km(e["lat"], e["lon"], *v[3:5]) for v in config.STATIONS.values())
        if near <= 100 * (m - 1.5):
            out.append({"id": "SGC" + e["id"], "time": str(e["time"]), "lat": e["lat"],
                        "lon": e["lon"], "depth": float(e["depth"] or 10), "mag": float(m),
                        "magType": e.get("magType") or "", "fuente": "SGC"})
    rng = random.Random(0)
    rng.shuffle(out)
    cuenta, elegidos = collections.Counter(), []
    for e in out:
        b = int(e["mag"] * 2)
        if cuenta[b] < SGC_POR_BIN:
            cuenta[b] += 1
            elegidos.append(e)
    print(f"SGC: {len(evs)} sismos, {len(out)} al alcance de las estaciones, {len(elegidos)} elegidos")
    return elegidos


def eventos(dias):
    """USGS (M>=3, toda la región) y SGC (pequeños, cerca de las estaciones). Un sismo que
    está en los dos (±10 s y 50 km) queda con la magnitud del SGC."""
    sgc = eventos_sgc(dias)
    usgs = [u for u in eventos_usgs(dias)
            if not any(abs(UTCDateTime(u["time"]) - UTCDateTime(g["time"])) <= 10
                       and _distance_km(u["lat"], u["lon"], g["lat"], g["lon"]) <= 50 for g in sgc)]
    return sorted(sgc + usgs, key=lambda e: e["time"])


def sensibilidades(client):
    out = {}
    for sta, (net, loc, cha, *_) in config.STATIONS.items():
        inv = client.get_stations(network=net, station=sta, location=loc or "--", channel=cha,
                                  level="response", endafter=UTCDateTime())
        ch = inv[0][0][0]
        out[sta] = ch.response.instrument_sensitivity.value  # cuentas por m/s
    return out


def descargar(cache, dias):
    cache.mkdir(parents=True, exist_ok=True)
    client = Client("EARTHSCOPE", timeout=120)
    sens_path = cache / "sensibilidad.json"
    if not sens_path.exists():
        sens_path.write_text(json.dumps(sensibilidades(client), indent=1))
    evs = eventos(dias)
    (cache / "eventos.json").write_text(json.dumps(evs))
    tp = TiemposP()
    local = threading.local()

    def uno(ev):
        path = cache / f"{ev['id']}.mseed"
        if path.exists():
            return
        if not hasattr(local, "c"):
            local.c = Client("EARTHSCOPE", timeout=120)
        t0 = UTCDateTime(ev["time"])
        bulk = []
        for sta, (net, loc, cha, lat, lon) in config.STATIONS.items():
            d = _distance_km(ev["lat"], ev["lon"], lat, lon)
            if d <= MAX_DIST_KM:
                p = t0 + float(tp(d, ev["depth"]))
                bulk.append((net, sta, loc or "--", cha, p - ANTES_S, p + DESPUES_S))
        try:
            st = local.c.get_waveforms_bulk(bulk) if bulk else None
        except Exception:  # sin datos para ese sismo
            st = None
        if st:
            st.write(str(path), format="MSEED")
        else:
            path.write_bytes(b"")

    with ThreadPoolExecutor(6) as ex:
        for i, _ in enumerate(ex.map(uno, evs)):
            if i % 200 == 0:
                print(f"{i}/{len(evs)} sismos", flush=True)


def medir(cache):
    """Una fila por sismo y estación: magnitud de catálogo, distancias y amplitudes medidas
    como en vivo (magnitud.medir) desde la onda P teórica."""
    tp = TiemposP()
    rows = []
    for ev in json.loads((cache / "eventos.json").read_text()):
        path = cache / f"{ev['id']}.mseed"
        if not path.exists() or not path.stat().st_size:
            continue
        t0 = UTCDateTime(ev["time"])
        st = read(str(path))
        st.merge(method=1, fill_value="interpolate")
        for tr in st:
            sta = tr.stats.station
            if sta not in config.STATIONS:
                continue
            lat, lon = config.STATIONS[sta][3:5]
            d = float(_distance_km(ev["lat"], ev["lon"], lat, lon))
            p = t0 + float(tp(d, ev["depth"]))
            if tr.stats.starttime > p - 30 or tr.stats.endtime < p + max(config.MAGNITUD_VENTANAS_S):
                continue
            rows.append({"id": ev["id"], "mag": ev["mag"], "lat": ev["lat"], "lon": ev["lon"],
                         "depth": ev["depth"], "sta": sta, "dist": d,
                         "R": float(np.hypot(d, ev["depth"])), "p": p,
                         "amps": magnitud.medir(tr, p)})
    return rows


def ajustar(rows, sens, tipo, w):
    """Coeficientes y correcciones por estación con las medidas que superan el ruido."""
    ok = [r for r in rows
          if r["amps"][tipo].get(w, 0) >= SNR_MIN * r["amps"]["ruido"][tipo] > 0]
    X = np.array([[np.log10(r["amps"][tipo][w] / sens[r["sta"]]), np.log10(r["R"]), 1]
                  for r in ok])
    y = np.array([r["mag"] for r in ok])
    # Cada medio grado de magnitud pesa lo mismo: si no, mandan los M4-5 (los más comunes
    # en el USGS), la pendiente sale chata y los sismos pequeños daban hasta +1,3 de más
    nbin = collections.Counter(int(m * 2) for m in y)
    sw = np.sqrt([1 / nbin[int(m * 2)] for m in y])
    coef, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
    res = y - X @ coef
    corr = {}
    for sta in config.STATIONS:
        rs = [e for e, r in zip(res, ok) if r["sta"] == sta]
        if len(rs) >= 5:
            corr[sta] = round(float(np.median(rs)), 2)
    res_c = np.array([e - corr.get(r["sta"], 0) for e, r in zip(res, ok)])
    return {"medidas": len(ok), "sismos": len({r["id"] for r in ok}),
            "a": round(float(coef[0]), 3), "b": round(float(coef[1]), 3),
            "c": round(float(coef[2]), 3), "sigma": round(float(res_c.std()), 2),
            "correccion": corr}


def calibrar(rows, sens):
    return {"sensibilidad": sens,
            "tipos": {tipo: {str(w): ajustar(rows, sens, tipo, w) for w in config.MAGNITUD_VENTANAS_S}
                      for tipo in magnitud.TIPOS}}


def validar(rows, sens, w, frac=0.75):
    """Ajusta con el primer 75 % de los sismos (por fecha) y prueba con el resto, calculando
    la magnitud del sismo como el sistema (magnitud.Magnitud.estimar) con la ubicación del
    catálogo. Devuelve [(magnitud de catálogo, error)]."""
    ids = list(dict.fromkeys(r["id"] for r in rows))  # en orden de fecha
    corte = set(ids[:int(len(ids) * frac)])
    tmp = Path(os.environ.get("TEMP", "/tmp")) / "magnitud_validacion.json"
    tmp.write_text(json.dumps(calibrar([r for r in rows if r["id"] in corte], sens)))
    m = magnitud.Magnitud(tmp)
    out = []
    for ev in ids[int(len(ids) * frac):]:
        rs = [r for r in rows if r["id"] == ev]
        amps = {r["sta"]: (r["p"], r["amps"]) for r in rs}
        loc = type("Loc", (), {"lat": rs[0]["lat"], "lon": rs[0]["lon"], "depth": rs[0]["depth"]})
        # con w = 5 la hora es la de 5 s tras la primera P: ninguna ventana de 30 s terminó
        now = min(r["p"] for r in rs) + (5 if w == 5 else 10 ** 6)
        # solo estaciones con señal: sin sismo no habría disparo
        amps = {s: a for s, a in amps.items()
                if any(a[1][t].get(w, 0) >= SNR_MIN * a[1]["ruido"][t] > 0 for t in magnitud.TIPOS)}
        est = m.estimar(amps, loc, now)
        if est:
            out.append((rs[0]["mag"], est["valor"] - rs[0]["mag"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True, type=Path)
    ap.add_argument("--dias", type=int, default=365)
    ap.add_argument("--solo-ajustar", action="store_true")
    a = ap.parse_args()
    if not a.solo_ajustar:
        descargar(a.cache, a.dias)
    sens = json.loads((a.cache / "sensibilidad.json").read_text())
    rows = medir(a.cache)
    out = {"fuente": f"USGS M>=3 y SGC M>=2 cerca de las estaciones, {a.dias} días hasta {UTCDateTime().date}; señal de EarthScope",
           "banda_vel_hz": list(config.BANDPASS),
           "banda_desp_hz": list(config.MAGNITUD_BANDA_DESP_HZ)}
    out.update(calibrar(rows, sens))
    for tipo, ws in out["tipos"].items():
        for w, k in ws.items():
            print(f"{tipo} {w} s: M = {k['a']:.2f}·log10(A) + {k['b']:.2f}·log10(R) + {k['c']:.2f}"
                  f"  ({k['medidas']} medidas de {k['sismos']} sismos, sigma {k['sigma']})")
    out["validacion"] = {}
    for w in config.MAGNITUD_VENTANAS_S:
        res = validar(rows, sens, w)
        mags, errs = np.array([m for m, _ in res]), np.array([e for _, e in res])
        linea = (f"validación {w} s (último 25 % de los sismos): {len(errs)} sismos, sesgo "
                 f"{errs.mean():+.2f}, desviación {errs.std():.2f}, "
                 f"{(abs(errs) <= 0.5).mean():.0%} dentro de ±0,5")
        por_mag = {}
        for lo, hi in ((2, 3), (3, 4), (4, 5), (5, 6), (6, 10)):
            k = (mags >= lo) & (mags < hi)
            if k.any():
                por_mag[f"M{lo}-{hi}"] = {"sismos": int(k.sum()), "sesgo": round(float(errs[k].mean()), 2)}
                linea += f" | M{lo}-{hi}: {k.sum()}, sesgo {errs[k].mean():+.2f}"
        print(linea)
        out["validacion"][str(w)] = {
            "sismos": len(errs), "sesgo": round(float(errs.mean()), 2),
            "desviacion": round(float(errs.std()), 2),
            "dentro_05": round(float((abs(errs) <= 0.5).mean()), 2), "por_magnitud": por_mag}
    path = Path(__file__).parent.parent / "magnitud.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"-> {path.resolve()}")


if __name__ == "__main__":
    main()
