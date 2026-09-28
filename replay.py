"""Prueba el detector con datos archivados del SGC, simulando llegada en tiempo real.

Uso: python replay.py 2026-09-27T21:57:52 [minutos_antes] [minutos_despues]
"""
import sys

from obspy import Stream, UTCDateTime
from obspy.clients.fdsn import Client

import config
from detector import Associator, StationTrigger

SGC_FDSN = "http://sismo.sgc.gov.co:8080"


def main():
    t0 = UTCDateTime(sys.argv[1])
    before = float(sys.argv[2]) if len(sys.argv) > 2 else 3
    after = float(sys.argv[3]) if len(sys.argv) > 3 else 4
    start, end = t0 - before * 60, t0 + after * 60
    # Las estaciones del SGC se piden al SGC; las demás (IU, EC) a IRIS
    sgc = Client(SGC_FDSN, _discover_services=False, service_mappings={
        "dataselect": SGC_FDSN + "/fdsnws/dataselect/1"})
    iris = Client("EARTHSCOPE")
    st = Stream()
    for sta, (net, loc, cha, *_) in config.STATIONS.items():
        try:
            client = sgc if net == "CM" else iris
            st += client.get_waveforms(net, sta, loc, cha, start, end)
        except Exception as e:
            print(f"{sta}: sin datos ({type(e).__name__})")
    st.merge(method=1, fill_value="interpolate")
    print(st.__str__(extended=True))

    assoc = Associator(
        on_detection=lambda d: print(f"\n*** DETECCIÓN [{d['level']}] {d['message']}\n    {d['stations']}"),
        on_update=lambda d: print(f"    + actualización [{d['level']}] {d['stations']}"),
    )
    triggers = {tr.stats.station: StationTrigger(tr.stats.station) for tr in st}
    # Simula paquetes de 2 s en orden cronológico
    step = 2.0
    t = start
    while t < end:
        for tr in st:
            chunk = tr.slice(t, t + step - tr.stats.delta)
            if chunk.stats.npts == 0:
                continue
            trig = triggers[tr.stats.station]
            onset = trig.add(chunk)
            if onset:
                print(f"disparo {tr.stats.station:5} {onset}  "
                      f"({onset - t0:+.0f} s desde el origen de referencia)")
                assoc.trigger(tr.stats.station, onset, trig.peak_ratio)
            elif trig.triggered:
                assoc.peak(tr.stats.station, trig.peak_ratio)
        t += step


if __name__ == "__main__":
    main()
