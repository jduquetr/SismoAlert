"""Búsqueda de eventos en los catálogos del SGC, USGS y EMSC."""
import json
import math
import ssl
import urllib.parse
import urllib.request

import certifi

from obspy import UTCDateTime

import config

USER_AGENT = "sismos-alerta-medellin/0.1 (prototipo personal)"
BOGOTA_OFFSET_S = -5 * 3600
# Certificados HTTPS de certifi en lugar de los del sistema: el Python de python.org en
# macOS no trae certificados instalados y todas las consultas HTTPS fallarían
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def _get_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as r:
        if r.status == 204:
            return None
        return json.loads(r.read().decode("utf-8"))


def _event(source, eid, time, lat, lon, depth, mag, magtype, place, status, url):
    return {
        "source": source, "id": eid, "time": UTCDateTime(time), "lat": lat, "lon": lon,
        "depth": depth, "mag": mag, "magtype": magtype, "place": place, "status": status,
        "url": url,
    }


def usgs(start, end):
    q = dict(format="geojson", starttime=str(start)[:19], endtime=str(end)[:19],
             minlatitude=config.REGION["minlat"], maxlatitude=config.REGION["maxlat"],
             minlongitude=config.REGION["minlon"], maxlongitude=config.REGION["maxlon"])
    d = _get_json("https://earthquake.usgs.gov/fdsnws/event/1/query?" + urllib.parse.urlencode(q))
    out = []
    for f in (d or {}).get("features", []):
        p, (lon, lat, depth) = f["properties"], f["geometry"]["coordinates"]
        out.append(_event("USGS", f["id"], p["time"] / 1000, lat, lon, depth, p["mag"],
                          p.get("magType"), p.get("place"), p.get("status"), p.get("url")))
    return out


def emsc(start, end):
    q = dict(format="json", starttime=str(start)[:19], endtime=str(end)[:19],
             minlat=config.REGION["minlat"], maxlat=config.REGION["maxlat"],
             minlon=config.REGION["minlon"], maxlon=config.REGION["maxlon"])
    d = _get_json("https://www.seismicportal.eu/fdsnws/event/1/query?" + urllib.parse.urlencode(q))
    out = []
    for f in (d or {}).get("features", []):
        p = f["properties"]
        out.append(_event("EMSC", p.get("unid", f.get("id")), p["time"], p["lat"], p["lon"],
                          p.get("depth"), p.get("mag"), p.get("magtype"), p.get("flynn_region"),
                          p.get("evtype"),
                          f"https://www.seismicportal.eu/eventdetails.html?unid={p.get('unid')}"))
    return out


def gdacs(days):
    """Sismos de GDACS (ONU + Comisión Europea) de los últimos `days` días, con su nivel de
    alerta de impacto (Green, Orange, Red). GDACS solo publica sismos grandes del mundo."""
    end = UTCDateTime()
    q = dict(eventlist="EQ", fromdate=(end - days * 86400).strftime("%Y-%m-%d"),
             todate=(end + 86400).strftime("%Y-%m-%d"), alertlevel="Green;Orange;Red")
    d = _get_json("https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH?"
                  + urllib.parse.urlencode(q), timeout=60)
    out = []
    for f in (d or {}).get("features", []):
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"][:2]
        sev = p.get("severitydata") or {}
        text = sev.get("severitytext") or ""
        depth = None
        if "Depth:" in text:
            try:
                depth = float(text.split("Depth:")[1].replace("km", "").strip())
            except ValueError:
                pass
        out.append({
            "id": f"{p['eventid']}-{p.get('episodeid')}", "eventid": p["eventid"],
            "time": p["fromdate"] + "Z", "lat": lat, "lon": lon, "mag": sev.get("severity"),
            "depth": depth, "alert": p.get("alertlevel"), "score": p.get("alertscore"),
            "country": p.get("country"), "name": p.get("name"),
            "url": (p.get("url") or {}).get("report"),
        })
    return sorted(out, key=lambda e: e["time"], reverse=True)


def emsc_felt_reports(unid):
    """Número de personas que reportaron haber sentido el sismo en EMSC (LastQuake)."""
    req = urllib.request.Request(
        "https://www.seismicportal.eu/testimonies-ws/api/search?"
        + urllib.parse.urlencode(dict(unids=unid, format="json")),
        headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20, context=SSL_CONTEXT) as r:
        body = r.read()
    if not body.strip():  # sin reportes: el servicio responde vacío
        return 0
    data = json.loads(body.decode("utf-8"))
    return data[0]["ev_nbtestimonies"] if data else 0


def sgc_biweekly(start, end):
    """Catálogo revisado del SGC. Solo trae eventos 'manual' y puede tardar."""
    fmt = "%Y-%m-%dT%H:%M:%S"
    q = dict(startdate=(start + BOGOTA_OFFSET_S).strftime(fmt),
             enddate=(end + BOGOTA_OFFSET_S).strftime(fmt))
    d = _get_json("https://api.sgc.gov.co/biweekly/biweekly_earthquakes?" + urllib.parse.urlencode(q))
    if d and "error" in d:
        raise RuntimeError(d["error"])
    out = []
    for f in (d or {}).get("features", []):
        p, (lon, lat, depth) = f["properties"], f["geometry"]["coordinates"]
        out.append(_event("SGC", f["id"], p["utcTime"].replace(" ", "T") + "Z", lat, lon, depth,
                          p["mag"], p.get("magType"), p.get("place"), p.get("status"),
                          f"https://www.sgc.gov.co/detallesismo/{f['id']}/resumen"))
    return out


def sgc_archive(start, end):
    """Feed del visor del SGC, con eventos preliminares. Requiere autorización del SGC."""
    d = _get_json("https://archive.sgc.gov.co/feed/v1.0.1/summary/five_days_all.json")
    out = []
    for f in (d or {}).get("features", []):
        p = f["properties"]
        lat, lon, depth = f["geometry"]["coordinates"]  # este feed usa [lat, lon, prof]
        t = UTCDateTime(p["utcTime"].replace(" ", "T") + "Z")
        if start <= t <= end:
            out.append(_event("SGC", f["id"], t, lat, lon, depth, p["mag"], p.get("magType"),
                              p.get("place"), p.get("status"),
                              f"https://www.sgc.gov.co/detallesismo/{f['id']}/resumen"))
    return out


def distance_km(lat1, lon1, lat2, lon2):
    r = math.radians
    dlat, dlon = r(lat2 - lat1), r(lon2 - lon1)
    h = math.sin(dlat / 2) ** 2 + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def priority(ev):
    """Clasificación provisional hasta tener la base de sismos sentidos en Medellín."""
    d = distance_km(*config.MEDELLIN, ev["lat"], ev["lon"])
    r = math.hypot(d, ev["depth"] or 0)  # distancia hipocentral
    m = ev["mag"] or 0
    if m >= 7 or (m >= 6 and r <= 500) or (m >= 5 and r <= 250) or (m >= 4 and r <= 100):
        level = "crítica"
    elif m >= 4.5 or (m >= 3 and r <= 300):
        level = "informativa"
    else:
        level = "silenciosa"
    return level, round(d), round(r)
