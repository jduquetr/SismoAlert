"""Genera sismicidad_previa.json: cuántos sismos ha habido en cada celda de la región.

Es la probabilidad de partida del ubicador (ubicador.py), como en Tamaribuchi et al. (2014):
conteos del catálogo en bloques de 0,5° de latitud y longitud y 50 km de profundidad. Así,
desde el primer disparo, los epicentros posibles se concentran donde de verdad tiembla
(Nido de Bucaramanga a ~150 km, Murindó, la costa Pacífica, el Caribe) y la profundidad
típica de cada zona sale del catálogo en vez de fijarse en 10 km.

Fuente: catálogo del USGS (ComCat), M>=2,5 desde 1990. Se pide por años porque el
servicio entrega como mucho 20.000 sismos por consulta.

Uso: python tools/sismicidad_previa.py
"""
import collections
import csv
import io
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config  # noqa: E402

URL = ("https://earthquake.usgs.gov/fdsnws/event/1/query?format=csv&starttime={y}-01-01"
       "&endtime={y2}-01-01&minlatitude={minlat}&maxlatitude={maxlat}&minlongitude={minlon}"
       "&maxlongitude={maxlon}&minmagnitude=2.5&orderby=time-asc")
CELL_DEG, CELL_KM = 0.5, 50
FIRST_YEAR = 1990


def main():
    counts = collections.Counter()
    total = 0
    for y in range(FIRST_YEAR, 2027):
        url = URL.format(y=y, y2=y + 1, **config.REGION)
        with urllib.request.urlopen(url, timeout=120) as r:
            rows = list(csv.DictReader(io.StringIO(r.read().decode())))
        for row in rows:
            lat, lon = float(row["latitude"]), float(row["longitude"])
            depth = float(row["depth"] or 0)
            counts[(int((lat - config.REGION["minlat"]) // CELL_DEG),
                    int((lon - config.REGION["minlon"]) // CELL_DEG),
                    int(max(depth, 0) // CELL_KM))] += 1
        total += len(rows)
        print(f"{y}: {len(rows)} sismos")
    out = {
        "fuente": f"USGS ComCat, M>=2.5, {FIRST_YEAR}-hoy",
        "sismos": total,
        "celda_grados": CELL_DEG, "celda_km": CELL_KM,
        "origen": [config.REGION["minlat"], config.REGION["minlon"]],
        # [fila de latitud, columna de longitud, capa de profundidad, sismos]
        "celdas": sorted([i, j, k, n] for (i, j, k), n in counts.items()),
    }
    path = os.path.join(os.path.dirname(__file__), "..", "sismicidad_previa.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"{total} sismos en {len(counts)} celdas -> {os.path.normpath(path)}")


if __name__ == "__main__":
    main()
