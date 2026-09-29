"""Alertas de sismos para Medellín.

Escucha estaciones del SGC por el SeedLink público de IRIS, detecta sismos con STA/LTA,
busca el evento en los catálogos del SGC, USGS y EMSC, y envía las alertas a una página
web local con notificaciones del navegador.

Uso: python server.py   y abrir http://127.0.0.1:8765
"""
import json
from copy import deepcopy
from functools import wraps
import logging
import queue
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from obspy import UTCDateTime

import config
import sources
import store
import telegram
import traveltime
from detector import Associator, StationTrigger, simultaneous_artifact
from emsc import EmscStream
from seedlink import SeedLinkClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sismos")
STATIC = Path(__file__).parent / "static"


def to_json(obj):
    if isinstance(obj, UTCDateTime):
        return obj.isoformat() + "Z"
    raise TypeError(type(obj))


class Hub:
    """Estado compartido y difusión de eventos a los navegadores conectados (SSE)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.clients = []
        self.detections = {}  # id -> detección
        self.log = []

    def subscribe(self):
        q = queue.Queue(maxsize=100)
        with self.lock:
            self.clients.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)

    def publish(self, kind, data):
        msg = f"event: {kind}\ndata: {json.dumps(data, default=to_json, ensure_ascii=False)}\n\n"
        with self.lock:
            for q in list(self.clients):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    self.clients.remove(q)

    def note(self, text):
        log.info(text)
        entry = {"t": UTCDateTime(), "text": text}
        with self.lock:
            self.log = (self.log + [entry])[-100:]
        self.publish("log", entry)

    def upsert_detection(self, det, kind):
        with self.lock:
            self.detections[det["id"]] = deepcopy(det)
            if len(self.detections) > 30:
                self.detections.pop(next(iter(self.detections)))
        try:
            store.save(det)
        except Exception:
            log.exception("No se pudo guardar %s", det["id"])
        self.publish(kind, det)

    def snapshot(self):
        with self.lock:
            return deepcopy({"detections": list(self.detections.values())[::-1], "log": self.log[-30:]})


hub = Hub()
triggers = {s: StationTrigger(s) for s in config.STATIONS}


# ---------------------------------------------------------------- búsqueda en catálogos
PRIORITY_ORDER = ["silenciosa", "informativa", "crítica"]
catalog_lock = threading.RLock()
active = {}  # detecciones con búsqueda en curso: id -> detección


def serialized(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with catalog_lock:
            return fn(*args, **kwargs)
    return wrapped


def emsc_search(start, end):
    """REST completa el websocket: un caché parcial no oculta otros eventos."""
    return sources.emsc(start, end)


def catalog_sources():
    srcs = [("USGS", sources.usgs), ("EMSC", emsc_search)]
    if config.USE_SGC_BIWEEKLY:
        srcs.append(("SGC", sources.sgc_biweekly))
    if config.USE_SGC_ARCHIVE_FEED:
        srcs.insert(0, ("SGC-feed", sources.sgc_archive))
    return srcs


def in_window(det, ev):
    start, end = detection_window(det)
    return start <= ev["time"] <= end


def max_detection_km(mag):
    """Distancia máxima a la que un sismo de esa magnitud puede dar un disparo fuerte.

    Regla generosa ajustada a lo observado: M2 ~100 km, M3 ~250, M4 ~625, M4.8 ~1300
    (el M4.8 de República Dominicana disparó URI a ~1000 km).
    """
    return 100 * 2.5 ** ((mag or 0) - 2)


def detection_window(det):
    """Ventana de origen posible: desde antes del primer disparo hasta el último.

    El final va hasta el último disparo porque el primero puede ser ruido de otra estación
    segundos antes del sismo; arrival_misfit descarta luego los eventos que no encajan.
    """
    onsets = [UTCDateTime(v["onset"]) for v in det.get("stations", {}).values()]
    first = det["first_onset"]
    last = max(onsets + [first])
    return first - config.MATCH_BEFORE_S, last + config.MATCH_AFTER_S


def arrival_misfit(det, ev):
    """Qué tan bien explica el evento los disparos fuertes (segundos), o None si no puede.

    Para cada estación con disparo fuerte, las ondas del evento deben llegar entre la P
    (menos un margen) y la S (más un margen). Basta con que una estación encaje: así un
    disparo de ruido en otra estación, que a veces es el primero de la detección, no hace
    rechazar el sismo real. Y no se empareja un sismo pequeño y lejano de minutos antes.
    Sin disparos fuertes (alerta solo de catálogo) no hay nada que comprobar y devuelve 0.
    """
    strong = [(v["onset"], s) for s, v in det.get("stations", {}).items()
              if v["ratio"] >= config.MIN_RATIO and s in config.STATIONS]
    if not strong:
        return 0.0
    depth = ev.get("depth") or 0
    max_km = max_detection_km(ev.get("mag"))
    misfits = []
    for onset, sta in strong:
        lat, lon = config.STATIONS[sta][3:5]
        d = sources.distance_km(ev["lat"], ev["lon"], lat, lon)
        if d > max_km:
            continue  # un sismo de esa magnitud no dispara con fuerza a esa distancia
        obs = UTCDateTime(onset) - ev["time"]
        tp, ts = traveltime.p_time(d, depth), traveltime.s_time(d, depth)
        if tp - config.MATCH_TOLERANCE_S <= obs <= ts + config.MATCH_TOLERANCE_S:
            misfits.append(abs(obs - tp))
    return min(misfits) if misfits else None


def best_match(det, evs):
    scored = [(arrival_misfit(det, e), e) for e in evs]
    scored = [(m, e) for m, e in scored if m is not None]
    if not scored:
        return None
    # El que mejor explica los tiempos; a igualdad, el de mayor magnitud
    return min(scored, key=lambda x: (round(x[0] / 5), -(x[1]["mag"] or 0)))[1]


@serialized
def attach(det, name, ev):
    """Asocia un evento de catálogo a una detección y avisa si es nuevo o cambió."""
    if det.get("discarded"):
        return
    level, dist, hyp = sources.priority(ev)
    ev = dict(ev, priority=level, distance_km=dist, hypo_km=hyp)
    with catalog_lock:
        cat = det.setdefault("catalog", {})
        prev = cat.get(name)
        if prev and prev["id"] == ev["id"] and "felt_reports" in prev:
            ev["felt_reports"] = prev.get("felt_reports")
        if prev == ev:
            return
        cat[name] = ev
        det["priority"] = max((e["priority"] for e in cat.values()), key=PRIORITY_ORDER.index)
    verb = "actualiza" if prev else "confirma"
    hub.note(f"{name} {verb} {det['id']}: M{ev['mag']} {ev['place']}, "
             f"a {dist} km de Medellín ({level})")
    hub.upsert_detection(det, "catalog")
    telegram.catalog(det, name, ev)


def refresh_felt_reports(det):
    with catalog_lock:
        ev = deepcopy(det.get("catalog", {}).get("EMSC"))
    if not ev or det.get("discarded"):
        return
    try:
        n = sources.emsc_felt_reports(ev["id"])
    except Exception as exc:
        log.warning("Error consultando reportes de EMSC: %s", exc)
        return
    with catalog_lock:
        current = det.get("catalog", {}).get("EMSC")
        if not current or current["id"] != ev["id"] or det.get("discarded"):
            return
        if n != current.get("felt_reports"):
            current["felt_reports"] = n
            det["felt_reports"] = n
            hub.upsert_detection(det, "catalog")


def search_catalogs(det):
    """No mantiene el bloqueo de estado mientras consulta la red o espera."""
    age = max(0, UTCDateTime() - UTCDateTime(det.get("detected_at") or UTCDateTime()))
    deadline = time.monotonic() + max(0, config.SEARCH_DURATION_S - age)
    srcs = catalog_sources()
    with catalog_lock:
        det["catalog_status"] = {name: "pendiente" for name, _ in srcs}
    failed = False
    try:
        while time.monotonic() < deadline:
            with catalog_lock:
                if det.get("discarded"):
                    break
                start, end = detection_window(det)
            for name, fn in srcs:
                try:
                    evs = fn(start, end)
                    with catalog_lock:
                        det["catalog_status"][name] = "ok"
                        ev = best_match(det, evs)
                        if ev:
                            attach(det, name, ev)
                except Exception as exc:
                    with catalog_lock:
                        det["catalog_status"][name] = "error"
                    log.warning("Error consultando %s: %s", name, exc)
            refresh_felt_reports(det)
            with catalog_lock:
                complete = all(name in det["catalog"] for name, _ in srcs)
            delay = config.SEARCH_INTERVAL_S * (5 if complete else 1)
            time.sleep(max(0, min(delay, deadline - time.monotonic())))
    except Exception:
        failed = True
        log.exception("Búsqueda interrumpida para %s", det["id"])
    finally:
        with catalog_lock:
            active.pop(det["id"], None)
            det["search"] = ("descartada" if det.get("discarded") else
                             "error" if failed else "terminada")
            if not det.get("catalog") and not det.get("discarded"):
                telegram.no_match(det)
            hub.note(f"Fin de búsqueda para {det['id']}: {det['search']}")
            hub.upsert_detection(det, "update")


@serialized
def on_detection(det, catalog_event=None):
    with hub.lock:
        if det["id"] in hub.detections or det["id"] in active:
            return
    # Si EMSC avisó antes de llegar las ondas, enriquecer esa misma detección.
    if catalog_event is None and not det.get("test"):
        with hub.lock:
            known = dict(hub.detections)
        known.update(active)
        for old in known.values():
            ev = old.get("catalog", {}).get("EMSC")
            if (old.get("level") == "catálogo" and ev and not old.get("discarded")
                    and in_window(det, ev) and arrival_misfit(det, ev) is not None):
                old.update(stations=det["stations"], first_onset=det["first_onset"],
                           level=det["level"], message=det["message"])
                assoc.current = old
                hub.upsert_detection(old, "update")
                return
    det.setdefault("catalog", {})
    det["search"] = "buscando"
    active[det["id"]] = det  # registrar antes de arrancar el hilo
    hub.note(f"DETECCIÓN {det['id']} [{det['level']}]: {det['message']}")
    hub.upsert_detection(det, "detection")
    if catalog_event is None:
        telegram.detection(det)
    else:
        attach(det, "EMSC", catalog_event)  # un solo aviso, ya confirmado
    threading.Thread(target=search_catalogs, args=(det,), daemon=True).start()


@serialized
def on_update(det):
    hub.note(f"{det['id']} [{det['level']}]: estaciones {', '.join(det['stations'])}")
    reason = simultaneous_artifact(det)
    # La heurística de simultaneidad no invalida un evento ya confirmado.
    if reason and not det.get("discarded") and not det.get("catalog"):
        det["discarded"] = reason
        hub.note(f"{det['id']} descartada: {reason}")
        telegram.discarded(det, reason)
    elif not det.get("discarded"):
        telegram.level_change(det)
    hub.upsert_detection(det, "update")


@serialized
def on_emsc_event(ev, action):
    """Deduplica por id de catálogo incluso al terminar búsquedas o reiniciar."""
    if action not in {"create", "update"}:
        return
    with hub.lock:
        known = dict(hub.detections)
    known.update(active)  # preferir la detección mutable en curso
    if assoc.current:
        known[assoc.current["id"]] = assoc.current
    for det in known.values():
        if det.get("test") or det.get("discarded"):
            continue
        old = det.get("catalog", {}).get("EMSC")
        if (old and old["id"] == ev["id"]) or det["id"] == f"EMSC-{ev['id']}":
            attach(det, "EMSC", ev)
            return
    candidates = [d for d in known.values() if not d.get("test")
                  and not d.get("discarded") and d.get("stations")
                  and in_window(d, ev) and arrival_misfit(d, ev) is not None]
    if candidates:
        attach(min(candidates, key=lambda d: arrival_misfit(d, ev)), "EMSC", ev)
        return
    # No alertar del historial reenviado al reconectar.
    if not -60 <= UTCDateTime() - ev["time"] <= config.SEARCH_DURATION_S:
        return
    level, dist, _ = sources.priority(ev)
    if level == "silenciosa":
        return
    det = {
        "id": f"EMSC-{ev['id']}", "first_onset": ev["time"],
        "detected_at": UTCDateTime(), "stations": {}, "level": "catálogo",
        "message": (f"Reportado por EMSC sin detección de las estaciones: M{ev['mag']} "
                    f"{ev['place']}, a {dist} km de Medellín"),
    }
    on_detection(det, catalog_event=ev)


emsc_stream = EmscStream(on_emsc_event, note=hub.note)
assoc = Associator(on_detection, on_update, lock=catalog_lock)


# ---------------------------------------------------------------------------- SeedLink
def on_trace(trace):
    sta = trace.stats.station
    trig = triggers.get(sta)
    if not trig:
        return
    try:
        onset = trig.add(trace)
    except Exception:
        log.exception("Error procesando %s", sta)
        return
    if onset:
        log.info("Disparo %s %s (STA/LTA %.1f)", sta, onset, trig.peak_ratio)
        assoc.trigger(sta, onset, trig.peak_ratio)
    elif trig.triggered:
        assoc.peak(sta, trig.peak_ratio, trig.onset)


def seedlink_loop():
    delay = 5
    streams = [(net, sta, loc + cha) for sta, (net, loc, cha, *_) in config.STATIONS.items()]
    while True:
        hub.note(f"Conectando a {config.SEEDLINK_SERVER}")
        connected_at = time.time()
        try:
            SeedLinkClient(config.SEEDLINK_SERVER, streams, on_trace).run()
        except Exception as e:
            hub.note(f"SeedLink desconectado: {e}. Reintento en {delay} s")
        # Si la conexión duró, volver a empezar con espera corta
        delay = 5 if time.time() - connected_at > 300 else min(delay * 2, 300)
        time.sleep(delay)


# ------------------------------------------------- sismicidad de fondo del catálogo del SGC
_sgc_cache = {"at": 0.0, "generated": None, "rows": []}  # últimos SGC_BACKGROUND_MAX_DAYS días
_sgc_lock = threading.Lock()
SGC_FIELDS = ["lon", "lat", "depth", "mag", "time", "place", "status", "id"]


def refresh_sgc_background():
    """Consulta al SGC los últimos SGC_BACKGROUND_MAX_DAYS días (ventanas de 14 días, lo que
    admite la API biweekly) y los deja en memoria en formato compacto."""
    if not config.USE_SGC_BIWEEKLY:
        return
    end = UTCDateTime()
    t = end - config.SGC_BACKGROUND_MAX_DAYS * 86400
    events = {}
    while t < end:
        t2 = min(t + 14 * 86400, end)
        for ev in sources.sgc_biweekly(t, t2):
            events[ev["id"]] = ev
        t = t2
    rows = sorted(([round(ev["lon"], 3), round(ev["lat"], 3), ev["depth"], ev["mag"],
                    ev["time"].isoformat()[:19] + "Z", ev["place"], ev["status"], ev["id"]]
                   for ev in events.values()), key=lambda r: r[4])
    with _sgc_lock:
        _sgc_cache.update(at=time.time(), generated=UTCDateTime(), rows=rows)
    log.info("Catálogo del SGC actualizado: %d sismos en %d días", len(rows), config.SGC_BACKGROUND_MAX_DAYS)


def sgc_background_loop():
    while True:
        try:
            refresh_sgc_background()
        except Exception as e:
            log.warning("No se pudo actualizar el catálogo del SGC: %s", e)
        time.sleep(config.SGC_BACKGROUND_REFRESH_S)


def sgc_background(days):
    """Sismos del catálogo del SGC de los últimos `days` días, desde la copia en memoria."""
    days = max(1, min(config.SGC_BACKGROUND_MAX_DAYS, int(days)))
    with _sgc_lock:
        empty = not _sgc_cache["generated"]
    if empty:
        refresh_sgc_background()  # primera vez, si la página pide antes que el hilo
    with _sgc_lock:
        since = (UTCDateTime() - days * 86400).isoformat()[:19] + "Z"
        rows = [r for r in _sgc_cache["rows"] if r[4] >= since]
        return {"available": bool(_sgc_cache["generated"]),
                "reason": None if config.USE_SGC_BIWEEKLY else "SGC desactivado en esta instalación",
                "days": days, "generated": _sgc_cache["generated"],
                "refresh_s": config.SGC_BACKGROUND_REFRESH_S, "count": len(rows),
                "fields": SGC_FIELDS, "events": rows}


def station_info():
    """Estado de cada estación junto con su red y ubicación (para la lista y el mapa)."""
    out = []
    for sta, (net, loc, cha, lat, lon) in config.STATIONS.items():
        out.append(dict(triggers[sta].status(), network=net, channel=f"{loc}.{cha}".lstrip("."),
                        lat=lat, lon=lon, group=config.STATION_GROUPS.get(sta)))
    return out


def recent_detections(seconds):
    """Detecciones reales (sin pruebas ni descartadas) en los últimos `seconds`."""
    return store.count_recent(seconds)


def status_loop():
    while True:
        hub.publish("stations", station_info())
        time.sleep(5)


# ------------------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", cors=False):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if cors:
            self._cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _cors_headers(self):
        """Deja leer el GeoJSON solo a las páginas del visor (config.VISOR_ORIGINS)."""
        origin = self.headers.get("Origin") or ""
        if re.match(config.VISOR_ORIGINS, origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            # Chrome pide este permiso cuando una página pública llama a 127.0.0.1
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/sismos-detectados.geojson":
            # Antes de la primera detección real el archivo no existe: colección vacía.
            body = (store.GEOJSON.read_bytes() if store.GEOJSON.exists()
                    else '{"type": "FeatureCollection", "features": []}')
            self._send(200, body, "application/geo+json; charset=utf-8", cors=True)
        elif path == "/sgc-sismos":
            days = parse_qs(urlparse(self.path).query).get("dias", ["30"])[0]
            try:
                data = sgc_background(days)
            except Exception as e:
                log.warning("No se pudo consultar el catálogo del SGC: %s", e)
                self._send(502, json.dumps({"error": f"No se pudo consultar el SGC: {e}"}))
                return
            self._send(200, json.dumps(data, default=to_json, ensure_ascii=False))
        elif path == "/state":
            snap = hub.snapshot()
            snap["stations"] = station_info()
            snap["medellin"] = config.MEDELLIN
            self._send(200, json.dumps(snap, default=to_json, ensure_ascii=False))
        elif path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            q = hub.subscribe()
            try:
                self.wfile.write(b": conectado\n\n")
                self.wfile.flush()
                while True:
                    try:
                        msg = q.get(timeout=15)
                    except queue.Empty:
                        msg = ": ping\n\n"
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                hub.unsubscribe(q)
        else:
            self._send(404, '{"error": "no encontrado"}')

    def do_POST(self):
        url = urlparse(self.path)
        if url.path == "/test":
            # Simula una detección. Con ?t=<hora UTC> busca un sismo pasado en los catálogos.
            # El cuerpo puede traer las estaciones: {"HEL": {"onset": ..., "ratio": ...}, ...}
            qs = parse_qs(url.query)
            t = UTCDateTime(qs["t"][0]) if "t" in qs else UTCDateTime()
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            det = {
                "id": f"PRUEBA{t.strftime('%Y%m%d%H%M%S')}-{UTCDateTime().strftime('%H%M%S')}",
                "first_onset": t,
                "detected_at": UTCDateTime(),
                "test": True,
                "stations": body.get("stations") or {
                    "HEL": {"onset": str(t), "ratio": 20.0},
                    "RUS": {"onset": str(t + 20), "ratio": 12.0}},
            }
            assoc._set_level(det)
            on_detection(det)
            self._send(200, json.dumps({"ok": True, "id": det["id"]}))
        else:
            self._send(404, '{"error": "no encontrado"}')


def main():
    # Recuperar las detecciones guardadas para que la lista no se pierda al reiniciar
    saved = store.load_recent()
    with hub.lock:
        hub.detections = {d["id"]: deepcopy(d) for d in saved}
    telegram.restore(saved)
    for det in saved:
        if det.get("search") == "buscando" and not det.get("discarded"):
            with catalog_lock:
                active[det["id"]] = det
            threading.Thread(target=search_catalogs, args=(det,), daemon=True).start()
    if saved:
        log.info("Cargadas %d detecciones guardadas en %s", len(saved), store.GEOJSON)
    threading.Thread(target=seedlink_loop, daemon=True).start()
    emsc_stream.start()
    threading.Thread(target=sgc_background_loop, daemon=True).start()
    threading.Thread(target=status_loop, daemon=True).start()
    telegram.start(station_info, recent_detections)
    server = ThreadingHTTPServer((config.HTTP_HOST, config.HTTP_PORT), Handler)
    server.daemon_threads = True
    hub.note(f"Página de alertas en http://{config.HTTP_HOST}:{config.HTTP_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
