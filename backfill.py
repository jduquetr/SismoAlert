"""Agrega al archivo de sismos detecciones obtenidas corriendo el detector sobre datos pasados.

Para cada hora de origen dada, repite las formas de onda (como replay.py), toma la
detección que corresponde al sismo, busca el evento en SGC, USGS y EMSC y la guarda en
datos/sismos-detectados.geojson marcada como registro "repeticion". La hora de alerta
es estimada: último disparo que activó la detección más el retraso típico de SeedLink.

Uso: python backfill.py 2026-09-27T21:57:51 2026-09-26T06:38:16 ...
"""
import sys

from obspy import Stream, UTCDateTime
from obspy.clients.fdsn import Client

import config
import sources
import store
from detector import Associator, StationTrigger
from server import best_match, detection_window, PRIORITY_ORDER

SGC_FDSN = "http://sismo.sgc.gov.co:8080"
LATENCY_S = 12  # retraso típico de SeedLink medido en vivo


def waveforms(start, end):
    sgc = Client(SGC_FDSN, _discover_services=False,
                 service_mappings={"dataselect": SGC_FDSN + "/fdsnws/dataselect/1"})
    iris = Client("EARTHSCOPE")
    st = Stream()
    for sta, (net, loc, cha, *_) in config.STATIONS.items():
        try:
            st += (sgc if net == "CM" else iris).get_waveforms(net, sta, loc, cha, start, end)
        except Exception as e:
            print(f"  {sta}: sin datos ({type(e).__name__})")
    st.merge(method=1, fill_value="interpolate")
    return st


def detect(t0):
    """Corre el detector como si los datos llegaran en vivo; devuelve la detección del sismo."""
    start, end = t0 - 60, t0 + 180
    st = waveforms(start, end)
    found = []

    def on_detection(det):
        strong = [UTCDateTime(v["onset"]) for v in det["stations"].values()
                  if v["ratio"] >= config.MIN_RATIO] or [det["first_onset"]]
        det["detected_at"] = max(strong) + LATENCY_S
        det["detected_at_estimado"] = True
        found.append(det)

    assoc = Associator(on_detection, lambda det: None)
    triggers = {tr.stats.station: StationTrigger(tr.stats.station) for tr in st}
    t, step = start, 2.0
    while t < end:
        for tr in st:
            chunk = tr.slice(t, t + step - tr.stats.delta)
            if chunk.stats.npts == 0:
                continue
            trig = triggers[tr.stats.station]
            onset = trig.add(chunk)
            if onset:
                assoc.trigger(tr.stats.station, onset, trig.peak_ratio)
            elif trig.triggered:
                assoc.peak(tr.stats.station, trig.peak_ratio)
        t += step
    # La detección con disparos fuertes después del origen. No se usa first_onset porque
    # a veces lo fija un disparo de ruido de otra estación segundos antes del sismo.
    def after_origin(det):
        return sum(1 for v in det["stations"].values()
                   if v["ratio"] >= config.MIN_RATIO and t0 <= UTCDateTime(v["onset"]) <= t0 + 180)
    found = [d for d in found if after_origin(d)]
    return max(found, key=after_origin) if found else None


def add_catalogs(det):
    start, end = detection_window(det)
    det["catalog"] = {}
    for name, fn in [("SGC", sources.sgc_biweekly), ("USGS", sources.usgs), ("EMSC", sources.emsc)]:
        try:
            ev = best_match(det, fn(start, end))
        except Exception as e:
            print(f"  {name}: error {e}")
            continue
        if ev:
            level, dist, hyp = sources.priority(ev)
            det["catalog"][name] = dict(ev, priority=level, distance_km=dist, hypo_km=hyp)
    if det["catalog"]:
        det["priority"] = max((e["priority"] for e in det["catalog"].values()), key=PRIORITY_ORDER.index)
    emsc = det["catalog"].get("EMSC")
    if emsc:
        try:
            emsc["felt_reports"] = det["felt_reports"] = sources.emsc_felt_reports(emsc["id"])
        except Exception as e:
            print(f"  EMSC reportes: error {e}")


def main():
    for arg in sys.argv[1:]:
        t0 = UTCDateTime(arg)
        print(f"{t0}:")
        det = detect(t0)
        if not det:
            print("  el detector no lo detectó; no se guarda")
            continue
        det["registro"] = "repeticion"
        add_catalogs(det)
        store.save(det)
        cat = ", ".join(f"{k} M{v['mag']}" for k, v in det["catalog"].items()) or "sin catálogo"
        print(f"  {det['id']} [{det['level']}] estaciones {list(det['stations'])} -> {cat}")


if __name__ == "__main__":
    main()
