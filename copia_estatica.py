"""Genera docs/index.html: copia estática de la página de alertas para publicar en Vercel.

Toma static/index.html y le incluye los datos del servidor en ese momento (estaciones,
detecciones y registro), los estilos de Leaflet y un mapa base de contornos (Natural
Earth 1:50m) para usar sin conexión. La copia no necesita el servidor y no se actualiza.

Uso:
  python copia_estatica.py                   # datos del servidor local en marcha
  python copia_estatica.py estado.json       # datos de un /state guardado antes
Después: git add docs/index.html, commit y push; Vercel la despliega solo.
"""
import datetime
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
CACHE = ROOT / "datos" / "cache"
SERVER_STATE = "http://127.0.0.1:8765/state"
SERVER_SGC = "http://127.0.0.1:8765/sgc-sismos?dias=30"
LEAFLET_JS = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"
LEAFLET_CSS = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"
NATURAL_EARTH = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
                 "geojson/ne_50m_admin_0_countries.geojson")
REGION = (-95, -55, -12, 24)  # oeste, este, sur, norte: algo más amplia que la vista
CITIES = [["Bogotá", 4.711, -74.072], ["Cali", 3.452, -76.532], ["Barranquilla", 10.964, -74.796],
          ["Cartagena", 10.391, -75.479], ["Bucaramanga", 7.119, -73.123], ["Pasto", 1.214, -77.281],
          ["Quibdó", 5.694, -76.661], ["Quito", -0.180, -78.467], ["Panamá", 8.983, -79.519],
          ["Caracas", 10.480, -66.904], ["Maracaibo", 10.642, -71.612], ["Santo Domingo", 18.486, -69.931]]


def fetch(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "sismos-alerta/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def cached(name, url):
    path = CACHE / name
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(fetch(url), encoding="utf-8")
    return path.read_text(encoding="utf-8")


def basemap():
    """Países que tocan la región, con coordenadas redondeadas para que pese poco (~130 KB)."""
    path = CACHE / "contornos.json"
    if path.exists():
        return path.read_text(encoding="utf-8")
    west, east, south, north = REGION
    feats = []
    for f in json.loads(cached("ne_50m_admin_0_countries.geojson", NATURAL_EARTH))["features"]:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        keep = []
        for poly in polys:
            xs = [p[0] for ring in poly for p in ring]
            ys = [p[1] for ring in poly for p in ring]
            if max(xs) < west or min(xs) > east or max(ys) < south or min(ys) > north:
                continue
            keep.append([[[round(x, 3), round(y, 3)] for x, y in ring] for ring in poly])
        if keep:
            name = f["properties"].get("NAME_ES") or f["properties"]["NAME"]
            feats.append({"type": "Feature", "properties": {"n": name},
                          "geometry": {"type": "MultiPolygon", "coordinates": keep}})
    text = json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":"),
                      ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    return text


def replace(html, old, new):
    if old not in html:
        raise SystemExit(f"No se encontró en static/index.html: {old[:70]!r}. ¿Cambió la página?")
    return html.replace(old, new, 1)


def build(state, sgc=None, *, taken=None):
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    taken = taken or datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # The page handles snapshot mode itself, so live handlers and local tests stay shared.
    html = replace(html, f'<link rel="stylesheet" href="{LEAFLET_CSS}">',
                   "<style>" + cached("leaflet.min.css", LEAFLET_CSS) + "</style>")
    html = replace(html, f'<script src="{LEAFLET_JS}"></script>',
                   "<script>" + cached("leaflet.min.js", LEAFLET_JS) + "</script>")
    def script_json(value):
        # Prevent catalog text from closing the inline script element.
        return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")
    payload = (f"const SNAPSHOT = {script_json(state)};\n"
               f"const SNAPSHOT_TAKEN = {script_json(taken)};\n"
               f"const BASEMAP = {script_json(json.loads(basemap()))};\n"
               f"const CITIES = {script_json(CITIES)};\n"
               f"const SGC_SNAPSHOT = {script_json(sgc)};\n")
    html = replace(html, "<script>\nconst $ = (s) => document.querySelector(s);",
                   "<script>\n" + payload + "const $ = (s) => document.querySelector(s);")
    return html



def main():
    if len(sys.argv) > 1:
        state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    else:
        try:
            state = json.loads(fetch(SERVER_STATE, timeout=10))
        except OSError as e:
            raise SystemExit(f"No se pudo leer {SERVER_STATE} ({e}). Arranca el servidor o pasa un "
                             "archivo de estado: python copia_estatica.py estado.json")
    out = ROOT / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    # Sismicidad de fondo del SGC (30 días) desde el servidor, si está en marcha
    try:
        sgc = json.loads(fetch(SERVER_SGC, timeout=60))
    except (OSError, ValueError) as e:
        print(f"Sin catálogo del SGC en la copia ({e})")
        sgc = None
    out.write_text(build(state, sgc), encoding="utf-8")
    print(f"{out}: {out.stat().st_size // 1024} KB, {len(state['detections'])} detecciones")
    # El registro de sismos también se publica: el visor sismos-3d-colombia lo usa como
    # respaldo cuando no alcanza el servidor en vivo (vercel.json le da CORS)
    geo = ROOT / "datos" / "sismos-detectados.geojson"
    if geo.exists():
        dest = out.parent / geo.name
        dest.write_bytes(geo.read_bytes())
        count = json.loads(geo.read_text(encoding="utf-8"))["metadata"]["count"]
        print(f"{dest}: {count} sismos registrados")


if __name__ == "__main__":
    main()
