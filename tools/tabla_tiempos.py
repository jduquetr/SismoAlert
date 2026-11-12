"""Genera las tablas de tiempos de viaje de las primeras ondas P y S (modelo IASP91).

Antes, traveltime.py usaba un modelo de dos capas (corteza y manto con un retraso fijo) que
no distinguía la profundidad en las ondas que viajan por el manto: para un sismo del nido de
Bucaramanga (~150 km) daba la P en el epicentro a los 5 s, cuando IASP91 da 20 s. Ahora todo
(ubicador, emparejamiento con catálogos, tiempo de aviso, página) usa estas tablas, calculadas
con TauP de ObsPy e interpoladas:

- tiempos_p.json y tiempos_s.json: 0-4.000 km cada 10 km, 0-300 km de profundidad cada 10 km.
- static/tiempos.js: las dos, más gruesas, para la página (mismo resultado a ±0,5 s).

Uso: python tools/tabla_tiempos.py
"""
import json
from pathlib import Path

import numpy as np
from obspy.taup import TauPyModel

ROOT = Path(__file__).resolve().parent.parent
DIST_KM = np.arange(0, 4001, 10)
DEPTH_KM = np.arange(0, 301, 10)
KM_PER_DEG = 111.195
FASES = {"p": ["p", "P", "Pn", "Pg"], "s": ["s", "S", "Sn", "Sg"]}
# Malla de la página: cada 20 km y las profundidades donde la curva cambia más
PAGINA_DIST_PASO = 2
PAGINA_PROF = [0, 10, 20, 30, 40, 50, 60, 80, 100, 120, 150, 180, 210, 250, 300]


def tabla(model, fases):
    t = np.zeros((len(DEPTH_KM), len(DIST_KM)))
    for i, z in enumerate(DEPTH_KM):
        for j, d in enumerate(DIST_KM):
            arr = model.get_travel_times(source_depth_in_km=float(z),
                                         distance_in_degree=d / KM_PER_DEG, phase_list=fases)
            t[i, j] = min(a.time for a in arr)
        print(f"  {fases[0]}: profundidad {z} km lista")
    return t


def main():
    model = TauPyModel("iasp91")
    tablas = {}
    for fase, lista in FASES.items():
        t = tablas[fase] = tabla(model, lista)
        out = {"modelo": "iasp91", "fase": fase.upper(), "distancias_km": DIST_KM.tolist(),
               "profundidades_km": DEPTH_KM.tolist(), "tiempos_s": np.round(t, 2).tolist()}
        path = ROOT / f"tiempos_{fase}.json"
        path.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
        print(f"-> {path}")
    filas = [list(DEPTH_KM).index(z) for z in PAGINA_PROF]
    cols = slice(None, None, PAGINA_DIST_PASO)
    pagina = {"distancias_km": DIST_KM[cols].tolist(), "profundidades_km": PAGINA_PROF,
              **{fase: np.round(t[filas][:, cols], 1).tolist() for fase, t in tablas.items()}}
    js = ("// Generado por tools/tabla_tiempos.py: tiempos de viaje IASP91 de la primera P y S\n"
          "// (s), por profundidad (filas) y distancia epicentral (columnas). No editar a mano.\n"
          f"const TIEMPOS = {json.dumps(pagina, separators=(',', ':'))};\n")
    (ROOT / "static" / "tiempos.js").write_text(js, encoding="utf-8")
    print(f"-> {ROOT / 'static' / 'tiempos.js'}")


if __name__ == "__main__":
    main()
