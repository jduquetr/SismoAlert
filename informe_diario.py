"""Informe diario del sistema de alertas, enviado por Telegram.

Cruza las detecciones guardadas en datos/sismos-detectados.geojson con los catálogos del
SGC, USGS y EMSC de las últimas 24 h y, para cada sismo registrado, calcula cuánto antes
(o después) de la llegada de la onda S a Medellín salió la alerta. Añade las detecciones
sin sismo en catálogo (posibles falsas alarmas) y el estado del servicio.

Uso:
  .venv/bin/python informe_diario.py             enviar el informe de las últimas 24 h
  .venv/bin/python informe_diario.py --prueba    solo imprimirlo
  .venv/bin/python informe_diario.py --horas 48

Telegram: TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en el archivo .env de esta carpeta
(fuera de git). Se programa a diario con linux/instalar_informe.sh.
"""
import argparse
import html
import json
import os
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from obspy import UTCDateTime

import config
import sources
from traveltime import p_time, s_time

DIR = Path(__file__).parent
GEOJSON = DIR / "datos" / "sismos-detectados.geojson"
BOGOTA_OFFSET_S = -5 * 3600
# Sismos del catálogo que entran en el informe: los cercanos a Medellín o los grandes
NEAR_KM, NEAR_MIN_MAG, FAR_MIN_MAG = 300, 2.5, 4.0
# Un disparo de estación corresponde a un sismo si cae así de cerca de la onda P predicha
# (en la revisión del 29-sep, HEL marcó la P de forma sistemática ~5 s después del modelo)
P_EARLY_S, P_LATE_S = -8, 12
SERVICE = "sismoalert"


def load_env():
    env = DIR / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def bogota(t):
    return (UTCDateTime(t) + BOGOTA_OFFSET_S).strftime("%H:%M:%S")


def catalog(start, end):
    """Sismos de los tres catálogos, sin repetir: se prefiere el SGC, luego USGS y EMSC."""
    events, failed = [], []
    for name, fn in (("SGC", sources.sgc_biweekly), ("USGS", sources.usgs), ("EMSC", sources.emsc)):
        try:
            evs = fn(start, end)
        except Exception as e:
            failed.append(f"{name} ({e})")
            continue
        for ev in evs:
            if ev["mag"] is None:
                continue
            same = [x for x in events if abs(x["time"] - ev["time"]) < 20
                    and sources.distance_km(x["lat"], x["lon"], ev["lat"], ev["lon"]) < 60]
            if same:
                same[0].setdefault("also", []).append(name)
            else:
                events.append(ev)
    for ev in events:
        ev["km"] = sources.distance_km(*config.MEDELLIN, ev["lat"], ev["lon"])
        ev["s_medellin"] = ev["time"] + s_time(ev["km"], ev["depth"] or 0)
    keep = [ev for ev in events if (ev["km"] <= NEAR_KM and ev["mag"] >= NEAR_MIN_MAG)
            or ev["mag"] >= FAR_MIN_MAG]
    return sorted(keep, key=lambda e: e["time"]), len(events), failed


def detections(start, end):
    if not GEOJSON.exists():
        return []
    feats = json.loads(GEOJSON.read_text(encoding="utf-8"))["features"]
    out = []
    for f in feats:
        p = f["properties"]
        if p.get("alerta") and start <= UTCDateTime(p["alerta"]) <= end + 600:
            out.append(p)
    return out


def matching_triggers(ev, det):
    """Estaciones de la detección cuyo disparo coincide con la onda P predicha del sismo."""
    hits = []
    for st in det.get("resumen", {}).get("estaciones_en_orden", []):
        info = config.STATIONS.get(st["estacion"])
        if not info:
            continue
        km = sources.distance_km(info[3], info[4], ev["lat"], ev["lon"])
        resid = UTCDateTime(st["disparo"]) - (ev["time"] + p_time(km, ev["depth"] or 0))
        if P_EARLY_S < resid < P_LATE_S:
            hits.append((st["estacion"], resid))
    return hits


def cross(events, dets):
    """Asigna a cada sismo su primera alerta: por estaciones o, si no, por catálogo."""
    used = set()
    for ev in events:
        ev["alerts"] = []
        for d in dets:
            alert = UTCDateTime(d["alerta"])
            if not (ev["time"] <= alert <= ev["time"] + 3600):
                continue
            if d.get("nivel") == "catálogo":
                ids = {d.get("id"), (d.get("deteccion") or {}).get("id")}
                cat = (d.get("deteccion") or {}).get("catalog") or {}
                ids |= {c.get("id") for c in cat.values()}
                ids |= {f"{c.get('source')}-{c.get('id')}" for c in cat.values()}
                near = d.get("primera_senal") and abs(UTCDateTime(d["primera_senal"]) - ev["time"]) < 20
                if ev["id"] in ids or near:
                    ev["alerts"].append((alert, d, []))
                    used.add(d["id"])
            else:
                hits = matching_triggers(ev, d)
                if hits:
                    ev["alerts"].append((alert, d, hits))
                    used.add(d["id"])
        ev["alerts"].sort(key=lambda a: a[0])
    unmatched = [d for d in dets if d["id"] not in used and d.get("nivel") != "catálogo"]
    return unmatched


def journal(since_h):
    def run(*args):
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=60).stdout
        except Exception:
            return ""
    log = run("journalctl", "-u", SERVICE, "--no-pager", "-o", "cat", "--since", f"-{since_h}h")
    sysd = run("journalctl", "-u", SERVICE, "--no-pager", "--since", f"-{since_h}h")
    active = run("systemctl", "is-active", SERVICE).strip() or "desconocido"
    since = run("systemctl", "show", SERVICE, "-p", "ActiveEnterTimestamp", "--value").strip()
    return {
        "active": active,
        "since": since,
        "starts": sysd.count("Started "),
        "seedlink": log.count("Conectando a rtserve"),
        "sgc_403": log.count("403"),
        "errors": sum(1 for line in log.splitlines() if " ERROR " in line or "Traceback" in line),
        "gaps": sum(1 for line in log.splitlines() if "hueco" in line.lower()),
    }


def fmt_lag(s):
    return f"{abs(s):.1f} s {'antes' if s < 0 else 'después'} de la S"


def build(hours):
    end = UTCDateTime()
    start = end - hours * 3600
    events, total, failed = catalog(start, end)
    dets = detections(start, end)
    unmatched = cross(events, dets)
    j = journal(hours)
    e = html.escape

    day = (end + BOGOTA_OFFSET_S).strftime("%Y-%m-%d")
    lines = [f"<b>SismoAlert · informe {day}</b>",
             f"Últimas {hours} h, hasta las {bogota(end)} (Bogotá)", ""]

    lines.append(f"<b>Sismos registrados</b> ({len(events)} de {total} en la región; "
                 f"≤{NEAR_KM} km con M≥{NEAR_MIN_MAG} o M≥{FAR_MIN_MAG})")
    if not events:
        lines.append("Ninguno.")
    detected = 0
    for ev in events:
        src = ev["source"] + (f"+{'+'.join(ev['also'])}" if ev.get("also") else "")
        lines.append(f"• {bogota(ev['time'])} <b>M{ev['mag']:.1f}</b> {e(ev['place'] or '')} · "
                     f"{ev['km']:.0f} km · prof {ev['depth'] or 0:.0f} km · {src}")
        lines.append(f"   Onda S en Medellín: {bogota(ev['s_medellin'])}")
        if not ev["alerts"]:
            lines.append("   ✗ Sin alerta")
            continue
        detected += 1
        for alert, d, hits in ev["alerts"][:2]:
            lag = alert - ev["s_medellin"]
            how = (", ".join(f"{s} {r:+.0f}s" for s, r in hits) if hits else "por catálogo")
            mark = "✅" if lag < 0 else "⚠️"
            lines.append(f"   {mark} Alerta {bogota(alert)} ({e(d.get('nivel') or '')}; {how}): "
                         f"<b>{fmt_lag(lag)}</b>")
    lines.append("")

    station_dets = [d for d in dets if d.get("nivel") != "catálogo"]
    lines.append(f"<b>Detecciones de las estaciones:</b> {len(station_dets)}")
    lines.append(f"Sismos con alerta: {detected} de {len(events)}")
    if unmatched:
        lines.append(f"Sin sismo en catálogo (posibles falsas): {len(unmatched)}")
        for d in unmatched[:12]:
            sts = ", ".join(s["estacion"] for s in d["resumen"].get("estaciones_en_orden", []))
            lines.append(f"   · {bogota(d['alerta'])} {e(d.get('nivel') or '')} ({sts})")
        if len(unmatched) > 12:
            lines.append(f"   · … y {len(unmatched) - 12} más")
    lines.append("")

    lines.append("<b>Servicio</b>")
    lines.append(f"Estado: {j['active']} desde {e(j['since'])}")
    lines.append(f"Arranques: {j['starts']} · conexiones SeedLink: {j['seedlink']} · "
                 f"errores: {j['errors']}")
    if j["sgc_403"]:
        lines.append(f"El SGC rechazó {j['sgc_403']} consultas del servidor (403)")
    if failed:
        lines.append("Catálogos que no respondieron al informe: " + e("; ".join(failed))[:300])
    return "\n".join(lines)


def send_telegram(text):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise SystemExit("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en .env")
    # Telegram admite 4096 caracteres por mensaje: se parte por líneas
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 4000:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    chunks.append(cur)
    for chunk in chunks:
        data = urllib.parse.urlencode({"chat_id": chat, "text": chunk, "parse_mode": "HTML",
                                       "disable_web_page_preview": "true"}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=30, context=sources.SSL_CONTEXT) as r:
            json.loads(r.read())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--horas", type=int, default=24)
    ap.add_argument("--prueba", action="store_true", help="imprimir sin enviar")
    args = ap.parse_args()
    load_env()
    text = build(args.horas)
    if args.prueba:
        print(text)
    else:
        send_telegram(text)
        print("Informe enviado")


if __name__ == "__main__":
    main()
