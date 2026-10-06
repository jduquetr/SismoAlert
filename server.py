"""Alertas de sismos para Medellín.

Escucha estaciones del SGC por el SeedLink público de IRIS, detecta sismos con STA/LTA,
busca el evento en los catálogos del SGC, USGS y EMSC, y envía las alertas a una página
web local con notificaciones del navegador.

Uso: python server.py   y abrir http://127.0.0.1:8765
"""
import json
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
            self.detections[det["id"]] = det
            if len(self.detections) > 30:
                self.detections.pop(next(iter(self.detections)))
        try:
            store.save(det)
        except Exception:
            log.exception("No se pudo guardar %s", det["id"])
        self.publish(kind, det)

    def snapshot(self):
        with self.lock:
            return {"detections": list(self.detections.values())[::-1], "log": self.log[-30:]}


hub = Hub()
triggers = {s: StationTrigger(s) for s in config.STATIONS}


# ---------------------------------------------------------------- búsqueda en catálogos
PRIORITY_ORDER = ["silenciosa", "informativa", "crítica"]
catalog_lock = threading.Lock()
active = {}  # detecciones con búsqueda en curso: id -> detección


def emsc_search(start, end):
    """EMSC desde el caché del websocket; si no está ahí, se consulta su servicio web."""
    return emsc_stream.search(start, end) or sources.emsc(start, end)


def catalog_sources():
    srcs = [("USGS", sources.usgs), ("EMSC", emsc_search)]
    if config.USE_SGC:
        srcs.insert(0, ("SGC", sources.sgc_biweekly))
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
    stations = [(v["onset"], s, v["ratio"]) for s, v in det.get("stations", {}).items()
                if s in config.STATIONS]
    if not stations:
        return 0.0  # alerta solo de catálogo: no hay disparos con qué comparar
    strong = [(t, s) for t, s, r in stations if r >= config.MIN_RATIO]
    if not strong:
        # Sin disparos fuertes se comparan todos: antes se aceptaba cualquier sismo de la
        # ventana y se emparejaban sismos pequeños y lejanos que no pudieron registrarse
        strong = [(t, s) for t, s, _ in stations]
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


def attach(det, name, ev):
    """Asocia un evento de catálogo a una detección y avisa si es nuevo o cambió."""
    level, dist, hyp = sources.priority(ev)
    ev = dict(ev, priority=level, distance_km=dist, hypo_km=hyp)
    with catalog_lock:
        cat = det.setdefault("catalog", {})
        prev = cat.get(name)
        if (prev and prev["id"] == ev["id"] and prev["mag"] == ev["mag"]
                and prev["status"] == ev["status"]):
            return
        if prev and prev["id"] == ev["id"]:
            ev["felt_reports"] = prev.get("felt_reports")
        cat[name] = ev
        det["priority"] = max((e["priority"] for e in cat.values()), key=PRIORITY_ORDER.index)
    verb = "actualiza" if prev else "confirma"
    hub.note(f"{name} {verb} {det['id']}: M{ev['mag']} {ev['place']}, "
             f"a {dist} km de Medellín ({level})")
    hub.upsert_detection(det, "catalog")


def refresh_felt_reports(det):
    ev = det.get("catalog", {}).get("EMSC")
    if not ev:
        return
    try:
        n = sources.emsc_felt_reports(ev["id"])
    except Exception as e:
        log.warning("Error consultando reportes de EMSC: %s", e)
        return
    if n != ev.get("felt_reports"):
        ev["felt_reports"] = n
        det["felt_reports"] = n
        if n:
            hub.note(f"{det['id']}: {n} personas reportaron en EMSC haberlo sentido")
        hub.upsert_detection(det, "catalog")


def search_catalogs(det):
    """Consulta los catálogos periódicamente hasta encontrar el sismo en todos."""
    deadline = time.time() + config.SEARCH_DURATION_S
    det.setdefault("catalog", {})
    det["search"] = "buscando"
    active[det["id"]] = det
    try:
        while time.time() < deadline:
            # Se recalcula en cada vuelta porque pueden sumarse estaciones a la detección
            start, end = detection_window(det)
            for name, fn in catalog_sources():
                try:
                    evs = fn(start, end)
                except Exception as e:
                    log.warning("Error consultando %s: %s", name, e)
                    continue
                ev = best_match(det, evs)
                if ev:
                    attach(det, name, ev)
            refresh_felt_reports(det)
            if all(n in det["catalog"] for n, _ in catalog_sources()):
                # Seguir un rato más por si cambian magnitudes, pero con menos frecuencia
                time.sleep(config.SEARCH_INTERVAL_S * 5)
            else:
                time.sleep(config.SEARCH_INTERVAL_S)
    finally:
        active.pop(det["id"], None)
    # Estado final, para que la página no siga mostrando "Buscando…" indefinidamente
    det["search"] = "terminada"
    if det["catalog"]:
        hub.note(f"Fin de la búsqueda en catálogos para {det['id']}")
    else:
        hub.note(f"{det['id']}: sin coincidencia en SGC, USGS ni EMSC tras "
                 f"{config.SEARCH_DURATION_S // 60} min (probable falsa alarma o sismo muy pequeño)")
    hub.upsert_detection(det, "update")


def on_detection(det):
    hub.note(f"DETECCIÓN {det['id']} [{det['level']}]: {det['message']}")
    hub.upsert_detection(det, "detection")
    threading.Thread(target=search_catalogs, args=(det,), daemon=True).start()


def on_update(det):
    hub.note(f"{det['id']} [{det['level']}]: estaciones {', '.join(det['stations'])}")
    reason = simultaneous_artifact(det)
    if reason and not det.get("discarded"):
        det["discarded"] = reason
        hub.note(f"{det['id']} descartada: {reason}")
    hub.upsert_detection(det, "update")


def on_emsc_event(ev, action):
    """Evento empujado por el websocket de EMSC."""
    matched = False
    for det in list(active.values()):
        if in_window(det, ev) and arrival_misfit(det, ev) is not None:
            attach(det, "EMSC", ev)
            matched = True
    if matched or action != "create":
        return
    level, dist, _ = sources.priority(ev)
    if level == "silenciosa":
        return
    # Sismo relevante que las estaciones no detectaron: alertar igual
    det = {
        "id": f"EMSC-{ev['id']}",
        "first_onset": ev["time"],
        "detected_at": UTCDateTime(),
        "stations": {},
        "level": "catálogo",
        "message": (f"Reportado por EMSC sin detección de las estaciones: M{ev['mag']} "
                    f"{ev['place']}, a {dist} km de Medellín"),
    }
    on_detection(det)


emsc_stream = EmscStream(on_emsc_event, note=hub.note)
assoc = Associator(on_detection, on_update)


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
        assoc.peak(sta, trig.peak_ratio)


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
    if not config.USE_SGC:
        log.info("SGC desactivado (config.USE_SGC): el mapa lo consultará desde el navegador")
        return
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
        failed_recently = time.time() - _sgc_cache.get("failed_at", 0) < 300
    if empty:
        # Primera vez, si la página pide antes que el hilo. Si acaba de fallar (p. ej. el SGC
        # bloquea esta IP), no reintentar con cada visita: el hilo lo reintenta a su ritmo.
        if failed_recently:
            raise RuntimeError("el catálogo del SGC no respondió hace poco; se reintentará")
        try:
            refresh_sgc_background()
        except Exception:
            with _sgc_lock:
                _sgc_cache["failed_at"] = time.time()
            raise
    with _sgc_lock:
        since = (UTCDateTime() - days * 86400).isoformat()[:19] + "Z"
        rows = [r for r in _sgc_cache["rows"] if r[4] >= since]
        return {"days": days, "generated": _sgc_cache["generated"],
                "refresh_s": config.SGC_BACKGROUND_REFRESH_S, "count": len(rows),
                "fields": SGC_FIELDS, "events": rows}


# ----------------------------------------------------------- avisos de GDACS (sismos grandes)
_gdacs = {"generated": None, "events": [], "seen": {}}  # seen: id -> nivel de alerta
_gdacs_lock = threading.Lock()


def gdacs_relevant(ev):
    """¿Avisar de este sismo? Alerta naranja/roja en el mundo, o cualquiera en la región."""
    r = config.REGION
    in_region = r["minlat"] <= ev["lat"] <= r["maxlat"] and r["minlon"] <= ev["lon"] <= r["maxlon"]
    return ev.get("alert") in config.GDACS_NOTIFY_LEVELS or in_region


def gdacs_loop():
    first = True
    while True:
        try:
            events = sources.gdacs(config.GDACS_DAYS)
            new = []
            with _gdacs_lock:
                for ev in events:
                    old = _gdacs["seen"].get(ev["id"])
                    if not first and old != ev["alert"]:  # nuevo, o cambió su nivel de alerta
                        new.append(ev)
                    _gdacs["seen"][ev["id"]] = ev["alert"]
                _gdacs.update(generated=UTCDateTime(), events=events)
            for ev in new:
                if gdacs_relevant(ev):
                    hub.note(f"GDACS: alerta {ev['alert']} · M{ev['mag']} {ev['name']} ({ev['time'][:16]} UTC)")
                    hub.publish("gdacs", ev)
            first = False
        except Exception as e:
            log.warning("No se pudo consultar GDACS: %s", e)
        time.sleep(config.GDACS_REFRESH_S)


def station_info():
    """Estado de cada estación junto con su red y ubicación (para la lista y el mapa)."""
    out = []
    for sta, (net, loc, cha, lat, lon) in config.STATIONS.items():
        out.append(dict(triggers[sta].status(), network=net, channel=f"{loc}.{cha}".lstrip("."),
                        lat=lat, lon=lon, group=config.STATION_GROUPS.get(sta)))
    return out


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
        elif path == "/gdacs":
            with _gdacs_lock:
                data = {"generated": _gdacs["generated"], "days": config.GDACS_DAYS,
                        "notify_levels": config.GDACS_NOTIFY_LEVELS, "events": _gdacs["events"]}
            self._send(200, json.dumps(data, default=to_json, ensure_ascii=False))
        elif path == "/fallas-gem.json":
            self._send(200, (STATIC / "fallas-gem.json").read_bytes(), "application/json; charset=utf-8")
        elif path == "/sgc-sismos":
            days = parse_qs(urlparse(self.path).query).get("dias", ["30"])[0]
            if not config.USE_SGC:
                # La página lo consulta entonces directamente desde el navegador
                self._send(200, json.dumps({"available": False, "reason": "SGC desactivado en este servidor"}))
                return
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
        hub.detections = {d["id"]: d for d in saved}
    if saved:
        log.info("Cargadas %d detecciones guardadas en %s", len(saved), store.GEOJSON)
    threading.Thread(target=seedlink_loop, daemon=True).start()
    emsc_stream.start()
    threading.Thread(target=sgc_background_loop, daemon=True).start()
    threading.Thread(target=gdacs_loop, daemon=True).start()
    threading.Thread(target=status_loop, daemon=True).start()
    server = ThreadingHTTPServer((config.HTTP_HOST, config.HTTP_PORT), Handler)
    server.daemon_threads = True
    hub.note(f"Página de alertas en http://{config.HTTP_HOST}:{config.HTTP_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
