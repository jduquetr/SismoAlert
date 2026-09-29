"""Avisos por Telegram.

Lee TELEGRAM_TOKEN y TELEGRAM_CHAT_ID del entorno; si faltan, no hace nada. Los mensajes
salen en un hilo aparte para no frenar la detección si Telegram tarda o no responde.

Qué se avisa:
- cada detección nueva (con sonido si es alta o media, en silencio si es baja);
- la primera confirmación en un catálogo y cada vez que sube la prioridad;
- el descarte de una detección y el fin de una búsqueda sin coincidencias;
- una estación que deja de enviar datos y cuando vuelve;
- un resumen diario a las TELEGRAM_DAILY_HOUR (hora de Bogotá) para saber que sigue vivo.
"""
import json
import logging
import os
import queue
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import config

log = logging.getLogger("sismos.telegram")
TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
PAGE_URL = os.environ.get("SISMOALERT_URL", "").strip()
BOGOTA = timezone(timedelta(hours=-5))

_q = queue.Queue(maxsize=200)
_sent = {}  # id de detección -> lo último avisado (nivel, prioridad, catálogos)


def enabled():
    return bool(TOKEN and CHAT_ID)


def send(text, silent=False):
    if not enabled():
        return
    try:
        _q.put_nowait((text, silent))
    except queue.Full:
        log.warning("Cola de Telegram llena; se descarta un mensaje")


def _post(text, silent):
    body = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
                       "disable_web_page_preview": True,
                       "disable_notification": silent}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                                 data=body, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15).read()


def _worker():
    while True:
        text, silent = _q.get()
        for attempt in range(4):
            try:
                _post(text, silent)
                break
            except Exception as e:
                log.warning("Telegram falló (intento %d): %s", attempt + 1, e)
                time.sleep(5 * (attempt + 1))


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _hora(t):
    """UTCDateTime u otra fecha -> '14:32:05' en hora de Bogotá."""
    try:
        dt = datetime.fromtimestamp(float(t.timestamp), tz=BOGOTA)
    except Exception:
        return ""
    return dt.strftime("%H:%M:%S")


def _link():
    return f"\n{PAGE_URL}" if PAGE_URL else ""


# ------------------------------------------------------------------------ detecciones
LEVEL_ICON = {"alta": "🔴", "media": "🟠", "baja": "🟡", "catálogo": "🔵"}
LOUD_LEVELS = {"alta", "media"}
LEVEL_RANK = {"baja": 1, "media": 2, "alta": 3}
PRIORITY_ICON = {"crítica": "🔴", "informativa": "🟡", "silenciosa": "⚪"}
PRIORITY_ORDER = ["silenciosa", "informativa", "crítica"]


def detection(det):
    level = det.get("level", "")
    prueba = "🧪 PRUEBA · " if det.get("test") else ""
    stations = ", ".join(det.get("stations") or {}) or "—"
    text = (f"{prueba}{LEVEL_ICON.get(level, '⚠️')} <b>Posible sismo · nivel {_esc(level)}</b>\n"
            f"Inicio: {_hora(det.get('first_onset'))} (hora Colombia)\n"
            f"Estaciones: {_esc(stations)}\n{_esc(det.get('message', ''))}{_link()}")
    _sent[det["id"]] = {"level": level, "priority": None, "catalogs": set()}
    send(text, silent=level not in LOUD_LEVELS and level != "catálogo")


def level_change(det):
    prev = _sent.get(det["id"])
    level = det.get("level")
    if not prev or LEVEL_RANK.get(level, 0) <= LEVEL_RANK.get(prev["level"], 0):
        return
    prev["level"] = level
    stations = ", ".join(det.get("stations") or {})
    send(f"{LEVEL_ICON.get(level, '⚠️')} <b>{_esc(det['id'])} sube a nivel {_esc(level)}</b>\n"
         f"Estaciones: {_esc(stations)}", silent=level not in LOUD_LEVELS)


def catalog(det, name, ev):
    """Primera confirmación en un catálogo o prioridad más alta que la ya avisada."""
    prev = _sent.setdefault(det["id"], {"level": det.get("level"), "priority": None,
                                        "catalogs": set()})
    level = ev.get("priority", "silenciosa")
    first = not prev["catalogs"]
    raised = (prev["priority"] is not None
              and PRIORITY_ORDER.index(level) > PRIORITY_ORDER.index(prev["priority"]))
    prev["catalogs"].add(name)
    if prev["priority"] is None or raised:
        prev["priority"] = level
    if not (first or raised):
        return
    prueba = "🧪 PRUEBA · " if det.get("test") else ""
    mag = ev.get("mag")
    text = (f"{prueba}{PRIORITY_ICON.get(level, '⚪')} <b>M{mag} · {_esc(ev.get('place', ''))}</b>\n"
            f"{_esc(name)} lo confirma · a {ev.get('distance_km')} km de Medellín "
            f"(prof. {ev.get('depth')} km)\nPrioridad: {_esc(level)}")
    if ev.get("url"):
        text += f"\n{_esc(ev['url'])}"
    send(text, silent=level != "crítica")


def discarded(det, reason):
    send(f"✖️ {_esc(det['id'])} descartada: {_esc(reason)}", silent=True)


def no_match(det):
    send(f"⚪ {_esc(det['id'])}: ningún catálogo lo registró en "
         f"{config.SEARCH_DURATION_S // 60} min (probable falsa alarma o sismo muy pequeño)",
         silent=True)


# ----------------------------------------------------------- salud de estaciones y resumen
STALE_S = int(os.environ.get("TELEGRAM_STALE_S", "600"))
DAILY_HOUR = int(os.environ.get("TELEGRAM_DAILY_HOUR", "7"))


def _health_loop(station_info, recent_detections):
    down = set()
    started = time.time()
    last_daily = None
    while True:
        time.sleep(60)
        try:
            info = station_info()
            # Dar 5 minutos al arrancar para que lleguen los primeros paquetes
            if time.time() - started > 300:
                now_down = {s["station"] for s in info
                            if s["last_packet_age_s"] is None
                            or s["last_packet_age_s"] > STALE_S}
                for sta in sorted(now_down - down):
                    send(f"⚠️ La estación {sta} no envía datos hace más de "
                         f"{STALE_S // 60} min", silent=True)
                for sta in sorted(down - now_down):
                    send(f"✅ La estación {sta} volvió a enviar datos", silent=True)
                if len(now_down) == len(info) and len(down) < len(info):
                    send("🚨 <b>Ninguna estación envía datos.</b> Revisa la conexión a IRIS "
                         "o el servidor.")
                down = now_down
            today = datetime.now(BOGOTA)
            if today.hour == DAILY_HOUR and last_daily != today.date():
                last_daily = today.date()
                ok = len(info) - len(down)
                dets = recent_detections(24 * 3600)
                send(f"✅ SismoAlert sigue vigilando · {ok}/{len(info)} estaciones con datos · "
                     f"{dets} detecciones en las últimas 24 h{_link()}", silent=True)
        except Exception:
            log.exception("Error en el chequeo de estaciones para Telegram")


def start(station_info, recent_detections):
    if not enabled():
        log.info("Telegram desactivado (faltan TELEGRAM_TOKEN y TELEGRAM_CHAT_ID)")
        return
    threading.Thread(target=_worker, daemon=True).start()
    threading.Thread(target=_health_loop, args=(station_info, recent_detections),
                     daemon=True).start()
    log.info("Avisos por Telegram activos")
