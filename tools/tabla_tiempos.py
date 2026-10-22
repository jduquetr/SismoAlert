"""Genera tiempos_p.json: tiempo de la primera onda P según distancia y profundidad.

traveltime.py usa un modelo de dos capas que basta para la página y para emparejar con
catálogos, pero no distingue sismos profundos (Nido de Bucaramanga, ~150 km): para ellos la
onda P viaja casi toda por el manto y llega varios segundos antes de lo que predice. El
ubicador (ubicador.py) necesita tiempos que sirvan a cualquier profundidad, así que se
tabulan con el modelo terrestre IASP91 (TauP de ObsPy) y luego se interpolan.

Uso: python tools/tabla_tiempos.py
"""
import json
import os

import numpy as np
from obspy.taup import TauPyModel

DIST_KM = np.arange(0, 2501, 10)
DEPTH_KM = np.arange(0, 301, 10)
KM_PER_DEG = 111.195


def main():
    model = TauPyModel("iasp91")
    table = np.zeros((len(DEPTH_KM), len(DIST_KM)))
    for i, z in enumerate(DEPTH_KM):
        for j, d in enumerate(DIST_KM):
            arr = model.get_travel_times(source_depth_in_km=float(z), distance_in_degree=d / KM_PER_DEG,
                                         phase_list=["p", "P", "Pn", "Pg"])
            table[i, j] = min(a.time for a in arr)
        print(f"profundidad {z} km lista")
    out = {"modelo": "iasp91", "distancias_km": DIST_KM.tolist(), "profundidades_km": DEPTH_KM.tolist(),
           "tiempos_s": np.round(table, 2).tolist()}
    path = os.path.join(os.path.dirname(__file__), "..", "tiempos_p.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"-> {os.path.normpath(path)}")


if __name__ == "__main__":
    main()
