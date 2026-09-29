"""Guarda todas las detecciones en un único archivo GeoJSON para el visor de sismos.

datos/sismos-detectados.geojson tiene un Feature por detección real y se reescribe
completo cada vez que llega una detección nueva o información nueva de una existente
(estaciones, catálogos, reportes "sentido").

- geometry: la ubicación del catálogo (la revisada del SGC si existe) como
  [lon, lat, prof]. Es null mientras ningún catálogo la publique; el visor
  sismos-3d-colombia salta esos registros al importar.
- properties: los campos que lee el visor (id, time, mag, depth, place) más el
  detalle completo de la detección en "deteccion" y los datos derivados en "resumen".

Las detecciones de prueba no se guardan, para no mezclarlas con sismos reales.
"""
import json
import logging
import threading
from pathlib import Path

from obspy import UTCDateTime

import config
import sources
import traveltime

log = logging.getLogger("sismos")
DATA = Path(__file__).parent / "datos"
GEOJSON = DATA / "sismos-detectados.geojson"
_lock = threading.Lock()
_records = None  # id de detección -> Feature; se carga del archivo la primera vez


def _to_json(obj):
    if isinstance(obj, UTCDateTime):
        return obj.isoformat() + "Z"
    raise TypeError(type(obj))


def preferred_location(det):
    """(fuente, evento) a usar: SGC revisado > SGC preliminar > USGS > EMSC."""
    cat = det.get("catalog") or {}
    for name in ("SGC-feed", "SGC"):
        if name in cat and cat[name].get("status") == "manual":
            return "SGC", cat[name]
    for name in ("SGC-feed", "SGC", "USGS", "EMSC"):
        if name in cat:
            return ("SGC" if name.startswith("SGC") else name), cat[name]
    return None, None


def summary(det):
    """Datos derivados: ubicación elegida, orden de estaciones y tiempos de llegada."""
    src, ev = preferred_location(det)
    stations = sorted(
        ({"estacion": s, "red": config.STATIONS[s][0] if s in config.STATIONS else None,
          "disparo": str(v["onset"]), "sta_lta": v["ratio"]} for s, v in det.get("stations", {}).items()),
        key=lambda x: x["disparo"])
    out = {"estaciones_en_orden": stations}
    if not ev:
        return out
    origin = UTCDateTime(ev["time"])
    dist = sources.distance_km(*config.MEDELLIN, ev["lat"], ev["lon"])
    depth = ev.get("depth") or 0
    for s in stations:
        if s["estacion"] in config.STATIONS:
            lat, lon = config.STATIONS[s["estacion"]][3:5]
            d = sources.distance_km(ev["lat"], ev["lon"], lat, lon)
            s["distancia_epicentro_km"] = round(d)
            s["desde_origen_s"] = round(UTCDateTime(s["disparo"]) - origin, 1)
            s["residuo_p_s"] = round(s["desde_origen_s"] - traveltime.p_time(d, depth), 1)
    tp, ts = traveltime.p_time(dist, depth), traveltime.s_time(dist, depth)
    out.update({
        "ubicacion_fuente": src,
        "ubicacion_revisada_sgc": src == "SGC" and ev.get("status") == "manual",
        "distancia_medellin_km": round(dist),
        "llegada_p_medellin_s": round(tp, 1), "llegada_s_medellin_s": round(ts, 1),
    })
    if det.get("detected_at"):
        alert = UTCDateTime(det["detected_at"]) - origin
        out["alerta_desde_origen_s"] = round(alert, 1)
        out["ventaja_sobre_onda_s_s"] = round(ts - alert, 1)
    return out


def _feature(det):
    src, ev = preferred_location(det)
    detail = json.loads(json.dumps(det, default=_to_json, ensure_ascii=False))
    # "en_vivo": detectada por el servidor; "repeticion": detector corrido sobre datos archivados
    props = {"id": ev["id"] if ev else det["id"], "deteccion_id": det["id"],
             "registro": det.get("registro", "en_vivo")}
    if ev:
        props.update({
            "time": ev["time"], "mag": ev["mag"], "magType": ev.get("magtype"),
            "depth": ev.get("depth"), "place": ev.get("place"), "source": src,
            "status": ev.get("status"),
        })
    props.update({
        "nivel": det.get("level"), "prioridad": det.get("priority"),
        "primera_senal": det.get("first_onset"), "alerta": det.get("detected_at"),
        "reportes_sentido": det.get("felt_reports"),
        "resumen": summary(det), "deteccion": detail, "actualizado": UTCDateTime(),
    })
    geometry = ({"type": "Point", "coordinates": [ev["lon"], ev["lat"], ev.get("depth") or 0]}
                if ev else None)
    return json.loads(json.dumps({"type": "Feature", "id": det["id"], "geometry": geometry,
                                  "properties": props}, default=_to_json, ensure_ascii=False))


def _load():
    global _records
    if _records is not None:
        return
    _records = {}
    if GEOJSON.exists():
        try:
            fc = json.loads(GEOJSON.read_text(encoding="utf-8"))
            for f in fc.get("features", []):
                _records[f["id"]] = f
        except Exception as e:
            # No sobrescribir un archivo que no se pudo leer: se aparta y se empieza otro
            backup = GEOJSON.with_name(f"sismos-detectados.danado-{UTCDateTime().strftime('%Y%m%d%H%M%S')}.geojson")
            GEOJSON.replace(backup)
            log.error("No se pudo leer %s (%s); se movió a %s", GEOJSON.name, e, backup.name)


def save(det):
    """Agrega o actualiza la detección y reescribe el archivo completo."""
    if det.get("test"):
        return
    with _lock:
        _load()
        _records[det["id"]] = _feature(det)
        features = sorted(_records.values(),
                          key=lambda f: f["properties"].get("primera_senal") or "")
        fc = {"type": "FeatureCollection",
              "metadata": {"titulo": "Sismos detectados por sismos-alerta (Medellín)",
                           "generado": UTCDateTime().isoformat() + "Z", "count": len(features),
                           "con_ubicacion": sum(1 for f in features if f["geometry"])},
              "features": features}
        DATA.mkdir(parents=True, exist_ok=True)
        tmp = GEOJSON.with_suffix(".tmp")
        tmp.write_text(json.dumps(fc, default=_to_json, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(GEOJSON)


def load_recent(limit=30):
    """Detecciones guardadas (las últimas `limit`), listas para volver a la lista en memoria."""
    with _lock:
        _load()
        feats = list(_records.values())
    recs = []
    for f in feats:
        det = f["properties"].get("deteccion")
        if not det:
            continue
        # Copia profunda: convertir las horas a UTCDateTime sobre los registros guardados
        # impedía después escribir el archivo (json no sabe serializarlas)
        det = json.loads(json.dumps(det))
        for k in ("first_onset", "detected_at"):
            if det.get(k):
                det[k] = UTCDateTime(det[k])
        for ev in (det.get("catalog") or {}).values():
            ev["time"] = UTCDateTime(ev["time"])
        recs.append(det)
    recs.sort(key=lambda r: r["first_onset"])
    return recs[-limit:]
