"""Replay reproducible sin interpolar huecos ni enviar avisos.

python replay.py 2026-09-27T21:57:51 10 5 --output resultado.json
--offline reutiliza las descargas en datos/replay; --set MIN_RATIO=10 compara umbrales.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from obspy import Stream, UTCDateTime, read
from obspy.clients.fdsn import Client

import config
from detector import Associator, StationTrigger, simultaneous_artifact

SGC_FDSN = "http://sismo.sgc.gov.co:8080"
EARTHSCOPE_FDSN = "https://service.earthscope.org"
PARAMETERS = ("THR_ON", "THR_OFF", "STA_S", "LTA_S", "MIN_RATIO",
              "LOCAL_ONLY_MIN_RATIO", "MIN_STATIONS", "MIN_STATIONS_REMOTE",
              "ASSOC_WINDOW_S", "DEAD_TIME_S")


def download(start, end, cache, offline=False):
    """Una entrada por solicitud exacta, con proveedor y hash verificables."""
    cache.mkdir(parents=True, exist_ok=True)
    st, coverage = Stream(), {}
    for sta, (net, loc, cha, *_) in config.STATIONS.items():
        provider = SGC_FDSN if net == "CM" else EARTHSCOPE_FDSN
        key = f"{provider}|{net}.{sta}.{loc}.{cha}|{start}|{end}"
        path = cache / (hashlib.sha256(key.encode()).hexdigest() + ".mseed")
        item = {"request": key, "provider": provider}
        try:
            if path.exists():
                data = read(str(path))
            elif offline:
                raise FileNotFoundError("No hay datos en caché")
            else:
                client = Client(provider, timeout=30, _discover_services=False,
                                service_mappings={"dataselect": provider + "/fdsnws/dataselect/1"})
                data = client.get_waveforms(net, sta, loc, cha, start, end)
                data.write(str(path), format="MSEED")
            # Unificar segmentos contiguos y mantener huecos como máscaras; split
            # vuelve a separarlos antes de alimentar exactamente el detector en vivo.
            data.merge(method=1, fill_value=None)
            data = data.split()
            item.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                        segments=len(data), samples=sum(tr.stats.npts for tr in data),
                        seconds=round(sum(tr.stats.npts / tr.stats.sampling_rate for tr in data), 2))
            st += data
        except Exception as exc:
            item["error"] = type(exc).__name__
            print(f"{sta}: sin datos ({type(exc).__name__})", flush=True)
        coverage[sta] = item
    return st, coverage


def simulate(st, start, end, reference, step=2.0):
    detections, updates, shots = {}, [], []
    clock = start

    def detected(det):
        det["detected_at"] = clock  # reloj de llegada simulado, no la hora de ejecución
        detections[det["id"]] = deepcopy(det)
        updates.append({"at": str(clock), "id": det["id"], "level": det["level"]})

    def updated(det):
        if simultaneous_artifact(det):
            det["discarded"] = simultaneous_artifact(det)
        detections[det["id"]] = deepcopy(det)
        updates.append({"at": str(clock), "id": det["id"], "level": det["level"]})

    assoc = Associator(detected, updated)
    triggers = {sta: StationTrigger(sta) for sta in config.STATIONS}
    t = start
    while t < end:
        clock = min(end, t + step)
        chunks = []
        for tr in st:
            chunk = tr.slice(t, min(end, t + step) - tr.stats.delta, nearest_sample=False)
            if chunk.stats.npts:
                chunks.append(chunk)
        for chunk in sorted(chunks, key=lambda tr: (tr.stats.starttime, tr.id)):
            sta = chunk.stats.station
            trig = triggers[sta]
            onset = trig.add(chunk)
            if onset:
                shots.append({"station": sta, "onset": str(onset), "ratio": float(trig.peak_ratio)})
                assoc.trigger(sta, onset, trig.peak_ratio)
            elif trig.triggered:
                assoc.peak(sta, trig.peak_ratio, trig.onset)
        t += step
    for det in detections.values():
        det["delay_from_reference_s"] = round(det["detected_at"] - reference, 2)
    return {"detections": list(detections.values()), "triggers": shots, "updates": updates}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin")
    parser.add_argument("before", type=float, nargs="?", default=3)
    parser.add_argument("after", type=float, nargs="?", default=4)
    parser.add_argument("--cache", type=Path, default=Path("datos/replay"))
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--set", action="append", default=[], metavar="PARAM=VALUE")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for setting in args.set:
        name, value = setting.split("=", 1)
        if name not in PARAMETERS:
            parser.error(f"Parámetro no permitido: {name}")
        setattr(config, name, type(getattr(config, name))(value))
    t0 = UTCDateTime(args.origin)
    start, end = t0 - args.before * 60, t0 + args.after * 60
    if args.before * 60 < config.LTA_S + 5 or args.after <= 0:
        parser.error("Se necesita calentamiento LTA+5 s y minutos después positivos")
    st, coverage = download(start, end, args.cache, args.offline)
    result = {"reference": str(t0), "start": str(start), "end": str(end),
              "parameters": {name: getattr(config, name) for name in PARAMETERS},
              "coverage": coverage, "packet_seconds": 2,
              "limitations": "Sin latencia de red ni publicación de catálogos; huecos preservados."}
    if not args.download_only:
        result.update(simulate(st, start, end, t0))
    encoded = json.dumps(result, default=str, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n")
    print(encoded, flush=True)
    if not st:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
