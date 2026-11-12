"""Tiempos de viaje de la primera onda P y S, interpolados de tablas IASP91.

Las tablas (tiempos_p.json, tiempos_s.json) salen de tools/tabla_tiempos.py con TauP de
ObsPy, de 0 a 4.000 km de distancia epicentral y de 0 a 300 km de profundidad. Reemplazan el
modelo de dos capas que se usó hasta nov-2026, que daba bien los sismos someros pero no los
profundos: a un sismo del nido de Bucaramanga (150 km) le daba la P en el epicentro a los 5 s,
y no a los 20 s, porque el retraso de la onda por el manto no dependía de la profundidad.

Lo usan el ubicador, el emparejamiento con catálogos (server.arrival_misfit, rectificar.py),
los residuos guardados (store.py) y el tiempo de aviso del informe diario. La página usa las
mismas tablas (static/tiempos.js).
"""
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent


class Tabla:
    """Tiempo (s) según distancia epicentral (km) y profundidad (km), interpolado.

    Acepta escalares o arreglos. Más allá de la última distancia se extrapola con la pendiente
    del final de la tabla; las profundidades se recortan al rango tabulado.
    """

    def __init__(self, path):
        t = json.loads(Path(path).read_text(encoding="utf-8"))
        self.dist = np.array(t["distancias_km"], dtype=float)
        self.depth = np.array(t["profundidades_km"], dtype=float)
        self.table = np.array(t["tiempos_s"], dtype=float)
        self._lenta = (self.table[:, -1] - self.table[:, -2]) / (self.dist[-1] - self.dist[-2])

    def __call__(self, dist_km, depth_km):
        dist_km = np.asarray(dist_km, dtype=float)
        d = np.clip(dist_km, self.dist[0], self.dist[-1])
        z = np.clip(depth_km, self.depth[0], self.depth[-1])
        i = np.clip(np.searchsorted(self.depth, z) - 1, 0, len(self.depth) - 2)
        j = np.clip(np.searchsorted(self.dist, d) - 1, 0, len(self.dist) - 2)
        fz = (z - self.depth[i]) / (self.depth[i + 1] - self.depth[i])
        fd = (d - self.dist[j]) / (self.dist[j + 1] - self.dist[j])
        t = self.table
        out = ((1 - fz) * ((1 - fd) * t[i, j] + fd * t[i, j + 1])
               + fz * ((1 - fd) * t[i + 1, j] + fd * t[i + 1, j + 1]))
        lejos = np.maximum(dist_km - self.dist[-1], 0)
        if np.any(lejos):
            out = out + lejos * ((1 - fz) * self._lenta[i] + fz * self._lenta[i + 1])
        return out


_P = Tabla(HERE / "tiempos_p.json")
_S = Tabla(HERE / "tiempos_s.json")


def p_time(dist_km, depth_km):
    """Tiempo (s) de la primera P desde el origen."""
    return float(_P(dist_km, depth_km or 0))


def s_time(dist_km, depth_km):
    """Tiempo (s) de la primera S desde el origen."""
    return float(_S(dist_km, depth_km or 0))
