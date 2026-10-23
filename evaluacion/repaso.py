"""Repaso en pseudo-tiempo-real: la alerta de verdad, alimentada con señal archivada.

Usa el detector, los dos asociadores y la magnitud tal como corren en el servidor, como una
caja negra, y escribe sus decisiones en el mismo formato que el servidor (decisiones.py), con
origen "repaso": la hora de cada decisión es la de la señal simulada, sin latencia (la
evaluación le suma la que se quiera estudiar). Así el mismo evaluador sirve para el registro
en vivo de la VM y para el archivo.

Dos formas:

- senal: para cada sismo se baja la señal vertical de las estaciones que votan (fuentes.py:
  SGC y EarthScope) y se pasa en trozos de PASO_S segundos; la magnitud se recalcula cada
  5 s como en el servidor. Las estaciones sin datos en esa fecha simplemente no participan.
- disparos: se vuelven a pasar los disparos ya guardados (el resumen del registro de la VM o
  datos/disparos.jsonl). No hay señal, así que no hay magnitud.

Uso:
  python -m evaluacion.repaso senal EVENTOS.pickle --salida decisiones.jsonl [--procesos 4]
  python -m evaluacion.repaso disparos REGISTRO.json.gz --salida decisiones.jsonl
"""
import argparse
import gzip
import json
import os
import pickle
import sys
import time
from multiprocessing import Pool

from obspy import UTCDateTime

import config
import decisiones
from asociador import BayesAssociator
from detector import Associator, StationTrigger
from ubicador import Malla

from .catalogo import clave, tiempo_p
from .fuentes import ClienteMixto

PASO_S = 2.0       # trozos de señal, como los paquetes de SeedLink
REFRESCO_S = 5.0   # el servidor recalcula la magnitud cada 5 s (server.refresh_loop)
ANTES_S = 90       # el STA/LTA necesita ~35 s para estabilizarse


def _copia(linea):
    return json.loads(json.dumps(linea, default=decisiones._json, ensure_ascii=False))


class _Repaso:
    """Los dos asociadores alimentados con los mismos disparos, con reloj simulado."""

    def __init__(self, malla, estaciones, amps=None):
        self.reloj = UTCDateTime(0)
        self.lineas = []
        self.bayes = BayesAssociator(self._anota("bayesiano", "nueva"),
                                     self._anota("bayesiano", "actualizacion"), malla=malla,
                                     alive=lambda: estaciones, clock=lambda: self.reloj,
                                     amps=amps)
        self.ventana = Associator(self._anota("ventana", "nueva"),
                                  self._anota("ventana", "actualizacion"))

    def _anota(self, asociador, evento):
        def f(det):
            self.lineas.append(_copia(decisiones.linea(det, evento, self.reloj, origen="repaso",
                                                       asociador=asociador)))
        return f

    def disparo(self, s, onset, ratio):
        for a in (self.bayes, self.ventana):
            a.trigger(s, onset, ratio)

    def pico(self, s, ratio):
        for a in (self.bayes, self.ventana):
            a.peak(s, ratio)


def duracion(ev):
    """Hasta la S en la estación más lejana que vota, más 60 s (máximo 400 s)."""
    tp = max(tiempo_p(ev, *v[3:5]) for v in config.STATIONS.values())
    return min(1.75 * tp + 60, 400)


def con_senal(ev, client, malla):
    """Decisiones de la alerta para un sismo, pasando su señal archivada."""
    t0 = ev["time"]
    ini, fin = t0 - ANTES_S, t0 + duracion(ev)
    bulk = [(n, s, loc or "--", ch, ini, fin) for s, (n, loc, ch, *_) in config.STATIONS.items()]
    st = client.get_waveforms_bulk(bulk)
    st.merge(method=1, fill_value="interpolate")
    con_datos = sorted({tr.stats.station for tr in st})
    trig = {s: StationTrigger(s) for s in con_datos}

    def amps(s):
        t = trig.get(s)
        return (t.onset, t.amps) if t and t.onset is not None else None

    r = _Repaso(malla, con_datos, amps)
    t, refresco = ini, ini
    while t < fin:
        r.reloj = t + PASO_S  # la decisión sale cuando el trozo terminó de llegar
        for tr in st:
            s = tr.stats.station
            trozo = tr.slice(t, t + PASO_S - 1e-4)
            if not trozo.stats.npts:
                continue
            onset = trig[s].add(trozo)
            if onset:
                r.disparo(s, onset, trig[s].peak_ratio)
            elif trig[s].triggered:
                r.pico(s, trig[s].peak_ratio)
        if r.reloj - refresco >= REFRESCO_S:
            r.bayes.refresh()
            refresco = r.reloj
        t += PASO_S
    for linea in r.lineas:
        linea["sismo_repasado"] = clave(ev)
    return r.lineas, con_datos


def leer_disparos(path):
    """Disparos únicos (hora, estación, sta/lta) de datos/disparos.jsonl o del resumen
    comprimido del registro de la VM ({id, t, lv, st: {estación: [hora, sta_lta]}})."""
    picks = {}
    if path.endswith(".gz"):
        for d in json.load(gzip.open(path, "rt", encoding="utf-8")):
            for s, (t, r) in d.get("st", {}).items():
                picks[(s, t)] = max(picks.get((s, t), 0), r)
    else:
        for line in open(path, encoding="utf-8"):
            p = json.loads(line)
            k = (p["station"], p["onset"])
            picks[k] = max(picks.get(k, 0), p["ratio"])
    return sorted(((UTCDateTime(t), s, r) for (s, t), r in picks.items()
                   if s in config.STATIONS), key=lambda x: x[0])


def con_disparos(picks, malla):
    r = _Repaso(malla, list(config.STATIONS))
    for t, s, ratio in picks:
        r.reloj = t
        r.disparo(s, t, ratio)
    return r.lineas


_worker = {}


def _trabajo(ev):
    if "client" not in _worker:
        _worker["client"] = ClienteMixto()
        _worker["malla"] = Malla()
    t = time.time()
    try:
        lineas, con_datos = con_senal(ev, _worker["client"], _worker["malla"])
        return clave(ev), lineas, f"{len(con_datos)} estaciones, {time.time() - t:.0f} s"
    except Exception as err:
        return clave(ev), None, f"{type(err).__name__}: {err}"[:200]


def repasar_eventos(evs, salida, procesos=4):
    """Repasa cada sismo y agrega sus decisiones a `salida` (retoma donde quedó)."""
    hechos_path = salida + ".hechos"
    hechos = set(open(hechos_path, encoding="utf-8").read().split()) if os.path.exists(hechos_path) else set()
    faltan = [e for e in evs if clave(e) not in hechos]
    print(f"repaso con señal: {len(faltan)} sismos por pasar ({len(hechos)} ya hechos)", file=sys.stderr)
    with Pool(procesos) as pool, open(salida, "a", encoding="utf-8") as f, \
            open(hechos_path, "a", encoding="utf-8") as h:
        for i, (k, lineas, nota) in enumerate(pool.imap_unordered(_trabajo, faltan), 1):
            if lineas is not None:
                for linea in lineas:
                    f.write(json.dumps(linea, ensure_ascii=False) + "\n")
                h.write(k + "\n")
                f.flush()
                h.flush()
            print(f"  {i}/{len(faltan)} {k}: {nota}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=("senal", "disparos"))
    ap.add_argument("entrada", help="senal: pickle con la lista de sismos; disparos: registro")
    ap.add_argument("--salida", required=True)
    ap.add_argument("--procesos", type=int, default=4)
    args = ap.parse_args()
    if args.modo == "senal":
        repasar_eventos(pickle.load(open(args.entrada, "rb")), args.salida, args.procesos)
    else:
        picks = leer_disparos(args.entrada)
        t = time.time()
        lineas = con_disparos(picks, Malla())
        with open(args.salida, "w", encoding="utf-8") as f:
            for linea in lineas:
                f.write(json.dumps(linea, ensure_ascii=False) + "\n")
        print(f"{len(picks)} disparos -> {len(lineas)} decisiones en {time.time() - t:.0f} s",
              file=sys.stderr)


if __name__ == "__main__":
    main()
