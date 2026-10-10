"""Rectifica un registro de detecciones contra los catálogos del SGC, USGS y EMSC.

Sirve sobre todo para máquinas que no pueden consultar al SGC (Azure: 403): se corre en un
equipo que sí puede (en Colombia), con el archivo de la máquina. Para cada detección:
vuelve a buscar el sismo con las reglas actuales (server.best_match), marca los artefactos
de la señal y calcula cuántos segundos antes o después de las ondas P y S en Medellín salió
la alerta. Escribe un archivo rectificado y un resumen en CSV.

Uso:
  python rectificar.py ARCHIVO.geojson                 informe en pantalla
  python rectificar.py ARCHIVO.geojson --escribir      además ARCHIVO-rectificado.geojson y .csv
"""
import argparse
import csv
import json
import sys
from pathlib import Path

from obspy import UTCDateTime

import config
import sources
import store
import traveltime
from detector import simultaneous_artifact, votes
from server import PRIORITY_ORDER, best_match, detection_window

# Retraso típico de SeedLink: si la detección no trae hora de alerta se estima con él
LATENCY_S = 12


def load_catalogs(start, end):
    """Catálogos completos del periodo, una sola vez (ventanas de 14 días para el SGC)."""
    cats = {"SGC": [], "USGS": [], "EMSC": []}
    t = start
    while t < end:
        t2 = min(t + 14 * 86400, end)
        cats["SGC"] += sources.sgc_biweekly(t, t2)
        t = t2
    cats["USGS"] = sources.usgs(start, end)
    cats["EMSC"] = sources.emsc(start, end)
    for name, evs in cats.items():
        print(f"  {name}: {len(evs)} sismos en el periodo", file=sys.stderr)
    return cats


def to_det(feature):
    det = json.loads(json.dumps(feature["properties"]["deteccion"]))
    det["first_onset"] = UTCDateTime(det["first_onset"])
    if det.get("detected_at"):
        det["detected_at"] = UTCDateTime(det["detected_at"])
    return det


def rectify(det, cats):
    """Vuelve a emparejar la detección; devuelve (det, fila de resumen)."""
    reason = simultaneous_artifact(det)
    if reason:
        det["discarded"] = reason
    start, end = detection_window(det)
    det["catalog"] = {}
    for name, evs in cats.items():
        ev = best_match(det, [e for e in evs if start <= e["time"] <= end])
        if ev:
            level, dist, hyp = sources.priority(ev)
            det["catalog"][name] = dict(ev, priority=level, distance_km=dist, hypo_km=hyp)
    det["priority"] = (max((e["priority"] for e in det["catalog"].values()), key=PRIORITY_ORDER.index)
                       if det["catalog"] else None)
    det["search"] = "terminada"
    det["rectificado"] = UTCDateTime()

    src, ev = store.preferred_location(det)
    row = {"deteccion": det["id"], "nivel": det.get("level"), "descartada": bool(det.get("discarded")),
           "estaciones": ",".join(s for s, v in sorted(det["stations"].items(), key=lambda x: x[1]["onset"])
                                  if v["ratio"] >= config.MIN_RATIO),
           "catalogos": "+".join(sorted(det["catalog"])) or ""}
    if ev:
        origin = ev["time"]
        dist = sources.distance_km(*config.MEDELLIN, ev["lat"], ev["lon"])
        depth = ev.get("depth") or 0
        tp, ts = traveltime.p_time(dist, depth), traveltime.s_time(dist, depth)
        alert = det.get("detected_at") or det["first_onset"] + LATENCY_S
        rel = alert - origin
        row.update(fuente=src, sismo=ev["id"], origen=str(origin)[:19], mag=ev["mag"], lugar=ev.get("place"),
                   prof_km=round(depth), dist_medellin_km=round(dist), alerta_s=round(rel, 1),
                   p_medellin_s=round(tp, 1), s_medellin_s=round(ts, 1),
                   antes_de_p_s=round(tp - rel, 1), antes_de_s_s=round(ts - rel, 1),
                   valida_para_tiempos=timing_status(det, ev, rel),
                   estaciones_coherentes=consistent_stations(det, ev))
    return det, row


def consistent_stations(det, ev):
    """Estaciones cuyo disparo explica el sismo: dentro de la distancia que alcanza su
    magnitud y entre la llegada de la onda P y la de la S. Con 1 sola, el resto de la
    detección pudo ser ruido que coincidió."""
    from server import max_detection_km
    depth, n = ev.get("depth") or 0, 0
    for s, v in det.get("stations", {}).items():
        if s not in config.STATIONS or not votes(s):  # las de observación no confirman
            continue
        d = sources.distance_km(ev["lat"], ev["lon"], *config.STATIONS[s][3:5])
        obs = UTCDateTime(v["onset"]) - ev["time"]
        if (d <= max_detection_km(ev.get("mag"))
                and traveltime.p_time(d, depth) - config.MATCH_TOLERANCE_S <= obs
                <= traveltime.s_time(d, depth) + config.MATCH_TOLERANCE_S):
            n += 1
    return n


def timing_status(det, ev, rel):
    """¿Sirve esta detección para medir la anticipación? 'si' o el motivo para no usarla.

    - Alerta solo de catálogo (EMSC): no la dieron las estaciones.
    - Alerta antes de que la onda P pudiera llegar a la estación más cercana del
      epicentro: la disparó ruido y el sismo coincidió después.
    - Más de 10 min después del origen: no es una alerta oportuna de ese sismo.
    """
    if not det.get("stations"):
        return "alerta solo de catálogo"
    nearest = min(sources.distance_km(ev["lat"], ev["lon"], *config.STATIONS[s][3:5])
                  for s in det["stations"] if s in config.STATIONS and votes(s))
    if rel < traveltime.p_time(nearest, ev.get("depth") or 0) - 2:
        return "alerta por ruido (antes de que llegara la onda P)"
    if rel > 600:
        return "alerta tardía (más de 10 min)"
    return "si"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("archivo")
    ap.add_argument("--escribir", action="store_true")
    args = ap.parse_args()
    path = Path(args.archivo)
    fc = json.loads(path.read_text(encoding="utf-8"))
    dets = [to_det(f) for f in fc["features"] if f["properties"].get("deteccion")]
    start = min(d["first_onset"] for d in dets) - 3600
    end = max(d["first_onset"] for d in dets) + 3600
    print(f"{len(dets)} detecciones del {str(start)[:10]} al {str(end)[:10]}", file=sys.stderr)
    cats = load_catalogs(start, end)

    rows, rectified = [], []
    for det in dets:
        det, row = rectify(det, cats)
        rows.append(row)
        rectified.append(det)

    real = [r for r in rows if r.get("sismo") and not r["descartada"]]
    n_disc = sum(r["descartada"] for r in rows)
    print(f"\nDetecciones: {len(rows)} | artefactos de señal: {n_disc} | con sismo de catálogo: {len(real)} | "
          f"sin sismo: {len(rows) - len(real) - n_disc}")
    excluded = [r for r in real if r["valida_para_tiempos"] != "si"]
    for motivo in sorted({r["valida_para_tiempos"] for r in excluded}):
        print(f"  no usadas para medir tiempos: {sum(r['valida_para_tiempos'] == motivo for r in excluded)} ({motivo})")
    # Un sismo puede quedar en varias detecciones: se cuenta la primera alerta válida
    by_quake = {}
    for r in sorted((r for r in real if r["valida_para_tiempos"] == "si"), key=lambda r: r["alerta_s"]):
        by_quake.setdefault(r["sismo"], r)
    quakes = sorted(by_quake.values(), key=lambda r: r["origen"])
    print(f"\nSismos distintos con alerta válida: {len(quakes)} (segundos de la alerta respecto a la llegada"
          " de las ondas a Medellín; positivo = la alerta llegó antes)")
    print(f"{'origen (UTC)':19} {'M':>4} {'lugar':32} {'dist':>5} {'nivel':6} {'coh':>3} {'alerta':>7} {'vs P':>7} {'vs S':>7}  fuente")
    for r in quakes:
        print(f"{r['origen']:19} {r['mag']:>4} {(r['lugar'] or '')[:32]:32} {r['dist_medellin_km']:>4}k {r['nivel']:6} "
              f"{r['estaciones_coherentes']:>3} {r['alerta_s']:>6.0f}s {r['antes_de_p_s']:>+6.0f}s "
              f"{r['antes_de_s_s']:>+6.0f}s  {r['fuente']}")
    if quakes:
        def summary(group, label):
            if not group:
                return
            bp = [r for r in group if r["antes_de_p_s"] > 0]
            bs = [r for r in group if r["antes_de_s_s"] > 0]
            med = sorted(r["antes_de_s_s"] for r in group)[len(group) // 2]
            print(f"  {label}: {len(group)} sismos | antes de la P: {len(bp)} | antes de la S: {len(bs)} "
                  f"| mediana respecto a la S: {med:+.0f} s")
        solid = [r for r in quakes if r["estaciones_coherentes"] >= 2]
        felt = [r for r in solid if r["mag"] >= 3.5 or r["dist_medellin_km"] <= 120]
        print("\nResumen (coh = estaciones coherentes con el sismo; con 1 puede ser coincidencia con ruido):")
        summary(quakes, "todos")
        summary(solid, "registro sólido (2+ estaciones coherentes)")
        summary(felt, "sólidos que pueden sentirse en Medellín (M≥3.5 o a ≤120 km)")
        print("\nAlerta antes de la onda P en Medellín:")
        for r in [r for r in quakes if r["antes_de_p_s"] > 0]:
            print(f"  {r['origen']} M{r['mag']} {r['lugar']} ({r['dist_medellin_km']} km): {r['antes_de_p_s']:+.0f} s; "
                  f"{r['estaciones_coherentes']} estación(es) coherente(s) de {r['estaciones']}")

    if args.escribir:
        tmp = path.with_name(path.stem + "-rectificado.geojson")
        store.DATA, store.GEOJSON, store._records = tmp.parent, tmp, {}
        for det in rectified:
            store.save(det)
        out_csv = path.with_name(path.stem + "-rectificado.csv")
        keys = sorted({k for r in rows for k in r})
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
        print(f"\nEscrito: {tmp}\nEscrito: {out_csv}")


if __name__ == "__main__":
    main()
