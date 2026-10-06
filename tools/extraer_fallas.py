"""Genera static/fallas-gem.json: fallas activas de Sur y Centroamérica (con el Caribe)
recortadas de GEM Global Active Faults (Styron y Pagani, 2020).

Mismo criterio que tools/extraer-fallas.mjs de sismos-3d-colombia, para otra región:
- se fija el commit de GEM para que el recorte sea reproducible y citable;
- se conservan los catálogos con nombres de falla: Active Tectonics of the Andes
  (Veloza et al., 2012), SARA (South America Risk Assessment) y GEM Central
  America-Caribbean; se descarta Bird (2003), que son límites de placa sin nombre;
- las coordenadas se redondean a 3 decimales (~100 m), suficiente a escala regional.
Licencia de los datos: CC BY-SA 4.0; el recorte la hereda.

Uso: python tools/extraer_fallas.py     (escribe static/fallas-gem.json; commitearlo)
"""
import datetime
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMIT_GEM = "56816508ad92fd6846dad1163b1c8c01376a2cd1"
URL_GEM = ("https://raw.githubusercontent.com/GEMScienceTools/gem-global-active-faults/"
           f"{COMMIT_GEM}/geojson/gem_active_faults.geojson")
# Sur y Centroamérica con el Caribe (y el sur de México, que comparte sistemas de fallas)
RECUADRO = {"o": -120, "e": -30, "s": -60, "n": 24}
CATALOGOS = ["Active Tectonics of the Andes", "SARA", "GEM_Central_Am_Carib"]
DECIMALES = 3


def tasa(texto):
    """"(2,,)" o "(0.5,0.1,1.0)" -> [preferida, mínima, máxima] en mm/año (None si falta)."""
    if not texto:
        return None
    vals = []
    for x in str(texto).strip("()").split(","):
        try:
            vals.append(float(x))
        except ValueError:
            vals.append(None)
    return vals if any(v is not None for v in vals) else None


def nombre(texto):
    """"SANTA MARTA- BUCARAMANGA_FAULT" -> "Santa Marta-Bucaramanga Fault"."""
    if not texto:
        return None
    t = re.sub(r"\s*-\s*", "-", str(texto).replace("_", " "))
    t = re.sub(r"\s+", " ", t).strip().lower()
    return re.sub(r"(^|[\s-])(\w)", lambda m: m.group(1) + m.group(2).upper(), t)


def dentro(p):
    lon, lat = p[:2]
    return RECUADRO["o"] <= lon <= RECUADRO["e"] and RECUADRO["s"] <= lat <= RECUADRO["n"]


def main():
    req = urllib.request.Request(URL_GEM, headers={"User-Agent": "sismos-alerta"})
    with urllib.request.urlopen(req, timeout=180) as r:
        gem = json.loads(r.read().decode("utf-8"))
    fallas = []
    for f in gem["features"]:
        p, g = f.get("properties") or {}, f.get("geometry")
        if not g or p.get("catalog_name") not in CATALOGOS:
            continue
        trazas = [g["coordinates"]] if g["type"] == "LineString" else (
            g["coordinates"] if g["type"] == "MultiLineString" else [])
        for traza in trazas:
            if len(traza) < 2 or not any(dentro(pt) for pt in traza):
                continue
            puntos = []
            for lon, lat, *_ in traza:
                pt = [round(lon, DECIMALES), round(lat, DECIMALES)]
                if not puntos or pt != puntos[-1]:  # sin puntos repetidos tras redondear
                    puntos.append(pt)
            if len(puntos) < 2:
                continue
            fallas.append({
                "nombre": nombre(p.get("name")), "tipo": p.get("slip_type") or None,
                "tasa": tasa(p.get("net_slip_rate")),
                "buzamiento": str(p["average_dip"]) if p.get("average_dip") else None,
                "catalogo": p["catalog_name"], "referencia": p.get("reference") or None,
                "traza": puntos,
            })
    salida = {
        "fuente": "GEM Global Active Faults Database (Styron & Pagani, 2020, Earthquake Spectra 36(1_suppl), 160-180)",
        "url": f"https://github.com/GEMScienceTools/gem-global-active-faults/tree/{COMMIT_GEM}",
        "licencia": "CC BY-SA 4.0", "catalogos": CATALOGOS, "recuadro": RECUADRO,
        "generado": datetime.date.today().isoformat(), "fallas": fallas,
    }
    out = ROOT / "static" / "fallas-gem.json"
    out.write_text(json.dumps(salida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    por_cat = {c: sum(1 for x in fallas if x["catalogo"] == c) for c in CATALOGOS}
    print(f"{out}: {len(fallas)} trazas, {out.stat().st_size // 1024} KB; por catálogo: {por_cat}")


if __name__ == "__main__":
    main()
