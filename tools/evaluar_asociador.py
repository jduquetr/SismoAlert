"""Compara el asociador actual con el bayesiano sobre un registro de detecciones.

Toma todos los disparos guardados en el registro (cada detección trae los de sus
estaciones), los vuelve a pasar en orden por los dos asociadores y empareja cada detección
resultante con los catálogos del SGC, USGS y EMSC del periodo, con las mismas reglas del
servidor (server.best_match). Una detección sin sismo en ningún catálogo es, casi siempre,
una falsa alarma. Para el bayesiano mide además el error de su epicentro frente al catálogo.

Solo usa las estaciones que votan (config.STATIONS); las regionales en observación no
deciden nada. Ojo: el registro solo guarda los disparos que terminaron en alguna detección,
así que ambos asociadores ven menos disparos sueltos de los que vio el servidor en vivo.

Uso: python tools/evaluar_asociador.py ARCHIVO.geojson [--cache catalogos.pickle] [--csv salida.csv]
"""
import argparse
import csv
import gzip
import os
import pickle
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import json  # noqa: E402

from obspy import UTCDateTime  # noqa: E402

import config  # noqa: E402
import sources  # noqa: E402
from asociador import BayesAssociator  # noqa: E402
from detector import Associator, simultaneous_artifact  # noqa: E402
from rectificar import load_catalogs  # noqa: E402
from server import best_match, detection_window  # noqa: E402
from ubicador import Malla, TiemposP  # noqa: E402


def load_dets(path):
    """Detecciones del registro: el geojson del servidor o el resumen comprimido que se baja
    de la VM ({id, t, lv, st: {estación: [hora, sta_lta]}}, .json.gz)."""
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return [{"id": d["id"], "level": d["lv"],
                     "stations": {s: {"onset": t, "ratio": r} for s, (t, r) in d["st"].items()}}
                    for d in json.load(f)]
    feats = json.load(open(path, encoding="utf-8"))["features"]
    return [f["properties"].get("deteccion") or f["properties"] for f in feats]


def load_picks(path):
    """Disparos únicos (estación, hora) del registro, con su relación STA/LTA máxima."""
    picks = {}
    for det in load_dets(path):
        if det.get("level") == "catálogo":
            continue
        for s, v in det.get("stations", {}).items():
            if s not in config.STATIONS:
                continue
            key = (s, v["onset"])
            picks[key] = max(picks.get(key, 0), v["ratio"])
    return sorted(((UTCDateTime(t), s, r) for (s, t), r in picks.items()), key=lambda x: x[0])


def run(assoc_cls, picks, **kw):
    """Pasa los disparos por un asociador; devuelve sus detecciones (estado final)."""
    dets = {}
    clock = {"now": None}

    def keep(det):
        dets[det["id"]] = det

    if assoc_cls is BayesAssociator:
        kw["clock"] = lambda: clock["now"]
    a = assoc_cls(on_detection=keep, on_update=keep, **kw)
    for t, s, r in picks:
        clock["now"] = t
        a.trigger(s, t, r)
    return list(dets.values())


def match(det, cats):
    """Regla del servidor: basta con que una estación encaje con el sismo (laxa)."""
    det = dict(det, first_onset=UTCDateTime(det["first_onset"]))
    start, end = detection_window(det)
    found = {}
    for name, evs in cats.items():
        ev = best_match(det, [e for e in evs if start <= e["time"] <= end])
        if ev:
            found[name] = ev
    ev = found.get("SGC") or found.get("USGS") or found.get("EMSC")
    return ev, sorted(found)


# Residuo admitido (s) entre un disparo y la P teórica del sismo de catálogo. Los disparos
# STA/LTA llegan en promedio ~3 s tarde (calibración del 25-sep al 10-oct)
RES_MIN_S, RES_MAX_S = -10, 15
TP = TiemposP()


def consistent(det, ev):
    """Disparos fuertes de la detección cuya hora encaja con la onda P del sismo."""
    ok, bad = [], []
    for s, v in det["stations"].items():
        if v["ratio"] < config.MIN_RATIO or s not in config.STATIONS:
            continue
        lat, lon = config.STATIONS[s][3:5]
        d = sources.distance_km(ev["lat"], ev["lon"], lat, lon)
        r = UTCDateTime(v["onset"]) - ev["time"] - float(TP(d, ev.get("depth") or 0))
        (ok if RES_MIN_S <= r <= RES_MAX_S else bad).append(s)
    return ok, bad


def strict_match(det, all_events):
    """Sismo que explica más disparos fuertes de la detección (estricta).

    Cuenta como real si al menos 2 disparos fuertes encajan; con un solo disparo fuerte
    (HEL sola), si encaja y el sismo está a menos de 300 km de Medellín.
    """
    t = UTCDateTime(det["first_onset"])
    best = None
    for ev in all_events:
        if not t - 900 <= ev["time"] <= t + 60:
            continue
        ok, bad = consistent(det, ev)
        if best is None or len(ok) > len(best[1]):
            best = (ev, ok, bad)
    if not best or not best[1]:
        return None, [], []
    ev, ok, bad = best
    near = sources.distance_km(*config.MEDELLIN, ev["lat"], ev["lon"]) <= 300
    if len(ok) >= 2 or (near and not bad):
        return ev, ok, bad
    return None, [], []


def summarize(name, dets, cats, rows):
    all_events = [e for evs in cats.values() for e in evs]
    by_level = {}
    errors = {"dentro": [], "fuera": []}
    matched_ids = set()
    n_ok = n_bad = 0
    alta_ok = alta_wrong = 0
    for det in dets:
        art = simultaneous_artifact(det)
        lax, names = match(det, cats)
        ev, ok, bad = (None, [], []) if art else strict_match(det, all_events)
        lv = det["level"]
        k = by_level.setdefault(lv, {"total": 0, "laxa": 0, "real": 0, "artefacto": 0})
        k["total"] += 1
        k["artefacto"] += bool(art)
        k["laxa"] += bool(lax and not art)
        if ev:
            k["real"] += 1
            n_ok += len(ok)
            n_bad += len(bad)
            matched_ids.add((round(ev["lat"], 1), round(ev["lon"], 1), str(ev["time"])[:16]))
            if lv == "alta":
                # "alta" dice que HEL lo registró: solo es correcto si el disparo de HEL encaja
                alta_ok += config.LOCAL_STATION in ok
                alta_wrong += config.LOCAL_STATION not in ok
        loc = det.get("ubicacion")
        err = None
        if ev and loc:
            err = sources.distance_km(loc["lat"], loc["lon"], ev["lat"], ev["lon"])
            nearest = min(sources.distance_km(ev["lat"], ev["lon"], *v[3:5]) for v in config.STATIONS.values())
            errors["dentro" if nearest <= 300 else "fuera"].append(err)
        rows.append({"asociador": name, "deteccion": det["id"], "nivel": lv,
                     "estaciones": ",".join(det["stations"]), "artefacto": bool(art),
                     "catalogos_regla_servidor": "+".join(names),
                     "sismo": f"M{ev['mag']} {ev['place']} {ev['time']}" if ev else "",
                     "encajan": ",".join(ok), "no_encajan": ",".join(bad),
                     "ubicacion": f"{loc['lat']},{loc['lon']},{loc['depth']}" if loc else "",
                     "error_km": round(err) if err is not None else ""})
    print(f"\n== {name}: {len(dets)} detecciones ==")
    print(f"{'nivel':8} {'total':>6} {'real':>6} {'falsa':>6} {'artefacto':>10} {'(regla servidor)':>17}")
    for lv in ("alta", "media", "baja"):
        k = by_level.get(lv)
        if k:
            print(f"{lv:8} {k['total']:6} {k['real']:6} {k['total'] - k['real'] - k['artefacto']:6} "
                  f"{k['artefacto']:10} {k['laxa']:17}")
    tot = sum(k["total"] for k in by_level.values())
    real = sum(k["real"] for k in by_level.values())
    art = sum(k["artefacto"] for k in by_level.values())
    print(f"{'todas':8} {tot:6} {real:6} {tot - real - art:6} {art:10} "
          f"{sum(k['laxa'] for k in by_level.values()):17}")
    if n_ok + n_bad:
        print(f"disparos fuertes ajenos dentro de las detecciones reales: {n_bad} de {n_ok + n_bad} "
              f"({100 * n_bad / (n_ok + n_bad):.0f} %)")
    print(f"nivel alta en detecciones reales: HEL sí lo registró {alta_ok}, "
          f"el disparo de HEL era de otra cosa {alta_wrong}")
    for where, e in errors.items():
        if e:
            e = sorted(e)
            print(f"error del epicentro, sismos {where} de la red (estación a <=300 km): "
                  f"mediana {statistics.median(e):.0f} km, p75 {e[int(.75 * (len(e) - 1))]:.0f} km (n={len(e)})")
    return matched_ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archivo")
    ap.add_argument("--cache", help="guardar/leer los catálogos del periodo en este archivo")
    ap.add_argument("--csv", help="detalle por detección")
    args = ap.parse_args()

    picks = load_picks(args.archivo)
    start, end = picks[0][0] - 600, picks[-1][0] + 600
    print(f"{len(picks)} disparos de {len(config.STATIONS)} estaciones, {start.date} a {end.date}")
    if args.cache and os.path.exists(args.cache):
        cats = pickle.load(open(args.cache, "rb"))
    else:
        cats = load_catalogs(start, end)
        if args.cache:
            pickle.dump(cats, open(args.cache, "wb"))

    rows = []
    t = time.time()
    old = run(Associator, picks)
    print(f"actual: {time.time() - t:.1f} s")
    t = time.time()
    new = run(BayesAssociator, picks, malla=Malla())
    print(f"bayesiano: {time.time() - t:.1f} s ({(time.time() - t) / len(picks) * 1000:.0f} ms por disparo)")
    a = summarize("actual (ventana de 120 s)", old, cats, rows)
    b = summarize("bayesiano (IPF adaptado)", new, cats, rows)
    print(f"\nsismos de catálogo detectados: actual {len(a)}, bayesiano {len(b)}, "
          f"ambos {len(a & b)}, solo actual {len(a - b)}, solo bayesiano {len(b - a)}")
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"detalle: {args.csv}")


if __name__ == "__main__":
    main()
