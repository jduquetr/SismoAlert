"""Mide las amplitudes de los disparos de un registro con la señal archivada en EarthScope.

Con ellas se pueden volver a pasar los disparos por el asociador bayesiano con magnitud y
con el término de amplitud del ubicador, como si fuera en vivo. Para cada disparo se guarda,
segundo a segundo durante los primeros 30 s, el máximo hasta ese momento del desplazamiento
y de la velocidad (magnitud.senal), y el ruido de antes del disparo: así el repaso puede dar
al asociador la amplitud que se conocía en cada instante, no la final.

Salida (JSON): {"ESTACIÓN|hora del disparo": {"desp": [31 máximos], "vel": [...],
"ruido": {"desp": n, "vel": n}}}. Si ya existe, solo mide los disparos que faltan.

Uso: python tools/amplitudes_disparos.py REGISTRO.json.gz SALIDA.json [--hilos 6]
"""
import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from obspy.clients.fdsn import Client

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config  # noqa: E402
import magnitud  # noqa: E402
from evaluar_asociador import load_picks  # noqa: E402

ANTES_S, DESPUES_S = 40, 32


def medir_disparo(tr, onset):
    df = tr.stats.sampling_rate
    i0 = int(round((onset - tr.stats.starttime) * df))
    out = {"ruido": {}}
    for tipo in magnitud.TIPOS:
        a = magnitud.senal(tr, tipo)
        out["ruido"][tipo] = float(a[max(0, i0 - int(25 * df)):max(1, i0 - int(2 * df))].max())
        acc = np.maximum.accumulate(a[i0:])
        out[tipo] = [float(acc[min(int(k * df), len(acc) - 1)]) for k in range(31)]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("registro")
    ap.add_argument("salida", type=Path)
    ap.add_argument("--hilos", type=int, default=6)
    a = ap.parse_args()
    picks = load_picks(a.registro)
    res = json.loads(a.salida.read_text()) if a.salida.exists() else {}
    todo = [(t, s) for t, s, _ in picks if f"{s}|{t}" not in res]
    print(f"{len(picks)} disparos, faltan {len(todo)}", flush=True)
    lock = threading.Lock()
    local = threading.local()

    def uno(item):
        t, s = item
        if not hasattr(local, "c"):
            local.c = Client("EARTHSCOPE", timeout=120)
        net, loc, cha, *_ = config.STATIONS[s]
        try:
            st = local.c.get_waveforms(net, s, loc or "--", cha, t - ANTES_S, t + DESPUES_S)
            st.merge(method=1, fill_value="interpolate")
            r = medir_disparo(st[0], t) if st else None
        except Exception:
            r = None  # sin señal archivada
        with lock:
            res[f"{s}|{t}"] = r

    with ThreadPoolExecutor(a.hilos) as ex:
        for i, _ in enumerate(ex.map(uno, todo)):
            if i % 200 == 0:
                print(f"{i}/{len(todo)}", flush=True)
                with lock:
                    a.salida.write_text(json.dumps(res))
    a.salida.write_text(json.dumps(res))
    print(f"{sum(1 for v in res.values() if v)} con señal de {len(res)}")


if __name__ == "__main__":
    main()
