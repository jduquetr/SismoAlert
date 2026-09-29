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
import math
import os
import queue
import threading
import time
import ssl
import urllib.error
import urllib.request
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from functools import wraps

import certifi

import config

log = logging.getLogger("sismos.telegram")
TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
PAGE_URL = os.environ.get("SISMOALERT_URL", "").strip()
BOGOTA = timezone(timedelta(hours=-5))

MAX_QUEUE_AGE_S = 600  # no reproducir alarmas antiguas tras una caída larga
_q = queue.Queue(maxsize=200)
_sent = OrderedDict()  # estado acotado de avisos aceptados por la cola
_lock = threading.RLock()
_started = False
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def serialized(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with _lock:
            result = fn(*args, **kwargs)
            while len(_sent) > 2048:
                _sent.popitem(last=False)
            return result
    return wrapped


def _state(det):
    return _sent.setdefault(det["id"], {"level": "", "priority": None,
                                         "catalogs": set(), "terminal": None})


@serialized
def restore(detections):
    """Restaurar máximos conocidos sin reanunciar el historial al reiniciar.

    Es deduplicación de mejor esfuerzo: guardar una detección no acredita entrega
    remota y Telegram no ofrece clave de idempotencia para sendMessage.
    """
    for det in detections:
        prev = _state(det)
        prev["level"] = det.get("level", "")
        cat = det.get("catalog") or {}
        prev["catalogs"] = set(cat)
        priorities = [e.get("priority") for e in cat.values()
                      if e.get("priority") in PRIORITY_ORDER]
        prev["priority"] = max(priorities, key=PRIORITY_ORDER.index) if priorities else None
        prev["terminal"] = "discarded" if det.get("discarded") else None


def enabled():
    return bool(TOKEN and CHAT_ID)


def send(text, silent=False):
    if not enabled():
        return False
    try:
        _q.put_nowait((text, silent, time.monotonic()))
        return True
    except queue.Full:
        log.warning("Cola de Telegram llena; se descarta un mensaje")
        return False


def _post(text, silent):
    body = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
                       "disable_web_page_preview": True,
                       "disable_notification": silent}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                                 data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15, context=SSL_CONTEXT) as response:
        result = json.loads(response.read())
    if not result.get("ok"):
        raise RuntimeError("Telegram no aceptó el mensaje")


def _worker():
    while True:
        text, silent, enqueued_at = _q.get()
        try:
            for attempt in range(4):
                if time.monotonic() - enqueued_at > MAX_QUEUE_AGE_S:
                    log.warning("Telegram: se descarta un mensaje vencido en la cola")
                    break
                delay = 5 * (attempt + 1)
                try:
                    _post(text, silent)
                    break
                except urllib.error.HTTPError as exc:
                    # No registrar la URL: contiene el token del bot.
                    log.warning("Telegram HTTP %s (intento %d)", exc.code, attempt + 1)
                    if exc.code == 429:
                        try:
                            retry_after = float(json.loads(exc.read())["parameters"]["retry_after"])
                            if math.isfinite(retry_after):
                                delay = max(1, retry_after)
                        except Exception:
                            pass
                    elif 400 <= exc.code < 500:
                        exc.close()
                        break
                    exc.close()
                except Exception as exc:
                    log.warning("Telegram falló: %s (intento %d)", type(exc).__name__, attempt + 1)
                if attempt < 3:
                    remaining = MAX_QUEUE_AGE_S - (time.monotonic() - enqueued_at)
                    time.sleep(max(0, min(delay, remaining + 0.01)))
            else:
                log.error("Telegram: mensaje no entregado tras cuatro intentos")
        finally:
            _q.task_done()


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
    return f"\n{_esc(PAGE_URL)}" if PAGE_URL else ""


# ------------------------------------------------------------------------ detecciones
LEVEL_ICON = {"alta": "🔴", "media": "🟠", "baja": "🟡", "catálogo": "🔵"}
LOUD_LEVELS = {"alta", "media"}
LEVEL_RANK = {"baja": 1, "media": 2, "alta": 3}
PRIORITY_ICON = {"crítica": "🔴", "informativa": "🟡", "silenciosa": "⚪"}
PRIORITY_ORDER = ["silenciosa", "informativa", "crítica"]


@serialized
def detection(det):
    prev = _state(det)
    if prev["level"] or prev["catalogs"] or prev["terminal"]:
        return
    level = det.get("level", "")
    prueba = "🧪 PRUEBA · " if det.get("test") else ""
    stations = ", ".join(det.get("stations") or {}) or "—"
    text = (f"{prueba}{LEVEL_ICON.get(level, '⚠️')} <b>Posible sismo · nivel {_esc(level)}</b>\n"
            f"Inicio: {_hora(det.get('first_onset'))} (hora Colombia)\n"
            f"Estaciones: {_esc(stations)}\n{_esc(det.get('message', ''))}{_link()}")
    if send(text, silent=level not in LOUD_LEVELS):
        prev["level"] = level


@serialized
def level_change(det):
    prev = _sent.get(det["id"])
    level = det.get("level")
    if det.get("discarded") or (prev and prev["terminal"]):
        return
    if not prev or not prev["level"]:
        detection(det)
        return
    if LEVEL_RANK.get(level, 0) <= LEVEL_RANK.get(prev["level"], 0):
        return
    stations = ", ".join(det.get("stations") or {})
    prueba = "🧪 PRUEBA · " if det.get("test") else ""
    if send(f"{prueba}{LEVEL_ICON.get(level, '⚠️')} <b>{_esc(det['id'])} sube a nivel {_esc(level)}</b>\n"
         f"Estaciones: {_esc(stations)}", silent=level not in LOUD_LEVELS):
        prev["level"] = level


@serialized
def catalog(det, name, ev):
    """Primera confirmación en un catálogo o prioridad más alta que la ya avisada."""
    if det.get("discarded"):
        return
    prev = _state(det)
    level = ev.get("priority", "silenciosa")
    if level not in PRIORITY_ORDER:
        level = "silenciosa"
    first = not prev["catalogs"]
    raised = (prev["priority"] is not None
              and PRIORITY_ORDER.index(level) > PRIORITY_ORDER.index(prev["priority"]))
    if not (first or raised):
        return
    prueba = "🧪 PRUEBA · " if det.get("test") else ""
    mag = ev.get("mag")
    text = (f"{prueba}{PRIORITY_ICON.get(level, '⚪')} <b>M{mag} · {_esc(ev.get('place', ''))}</b>\n"
            f"{_esc(name)} lo confirma · a {ev.get('distance_km')} km de Medellín "
            f"(prof. {ev.get('depth')} km)\nPrioridad: {_esc(level)}")
    if ev.get("url"):
        text += f"\n{_esc(ev['url'])}"
    if send(text, silent=level != "crítica"):
        prev["catalogs"].add(name)
        prev["priority"] = level


@serialized
def discarded(det, reason):
    prev = _state(det)
    if prev["terminal"] == "discarded":
        return
    prueba = "🧪 PRUEBA · " if det.get("test") else ""
    if send(f"{prueba}✖️ {_esc(det['id'])} descartada: {_esc(reason)}", silent=True):
        prev["terminal"] = "discarded"


@serialized
def no_match(det):
    prev = _state(det)
    if prev["terminal"] or det.get("catalog") or det.get("discarded"):
        return
    failures = [name for name, status in det.get("catalog_status", {}).items()
                if status != "ok"]
    if failures or det.get("search") == "error":
        text = (f"⚠️ {_esc(det['id'])}: búsqueda incompleta; no se pudo verificar "
                f"{_esc(', '.join(failures) or 'los catálogos')}. No permite descartar un sismo.")
    else:
        text = (f"⚪ {_esc(det['id'])}: sin coincidencias en los catálogos consultados "
                f"tras {config.SEARCH_DURATION_S // 60} min. Sin confirmación de catálogo.")
    if det.get("test"):
        text = "🧪 PRUEBA · " + text
    if send(text, silent=True):
        prev["terminal"] = "no_match"


# ----------------------------------------------------------- salud de estaciones y resumen
STALE_S = int(os.environ.get("TELEGRAM_STALE_S", "600"))
DAILY_HOUR = int(os.environ.get("TELEGRAM_DAILY_HOUR", "7"))


def _unhealthy(info):
    return {s["station"] for s in info
            if s["last_packet_age_s"] is None or s["last_packet_age_s"] > STALE_S
            or s.get("latency_s") is None or s["latency_s"] > STALE_S}


def _health_loop(station_info, recent_detections):
    down = set()  # transiciones aceptadas por la cola
    all_down_sent = False
    started = time.monotonic()
    last_daily = None
    while True:
        time.sleep(60)
        try:
            info = station_info()
            now_down = _unhealthy(info)
            if time.monotonic() - started > 300:
                for sta in sorted(now_down - down):
                    if send(f"⚠️ La estación {_esc(sta)} no tiene datos recientes "
                            f"(límite: {STALE_S // 60} min)", silent=True):
                        down.add(sta)
                for sta in sorted(down - now_down):
                    if send(f"✅ La estación {_esc(sta)} volvió a enviar datos", silent=True):
                        down.remove(sta)
                all_down = bool(info) and len(now_down) == len(info)
                if all_down and not all_down_sent:
                    all_down_sent = send("🚨 <b>Ninguna estación tiene datos recientes.</b> "
                                         "Revisa la conexión a IRIS o el servidor.")
                elif not all_down:
                    all_down_sent = False
            today = datetime.now(BOGOTA)
            if today.hour == DAILY_HOUR and last_daily != today.date():
                ok = len(info) - len(now_down)
                dets = recent_detections(24 * 3600)
                if send(f"✅ SismoAlert sigue vigilando · {ok}/{len(info)} estaciones con datos · "
                        f"{dets} detecciones en las últimas 24 h{_link()}", silent=True):
                    last_daily = today.date()
        except Exception:
            log.exception("Error en el chequeo de estaciones para Telegram")


@serialized
def start(station_info, recent_detections):
    global _started
    if _started:
        return
    if not enabled():
        log.info("Telegram desactivado (faltan TELEGRAM_TOKEN y TELEGRAM_CHAT_ID)")
        return
    _started = True
    threading.Thread(target=_worker, daemon=True).start()
    threading.Thread(target=_health_loop, args=(station_info, recent_detections),
                     daemon=True).start()
    log.info("Avisos por Telegram activos")
