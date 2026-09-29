"""Eventos de EMSC en tiempo real por websocket (sin tener que consultar cada minuto)."""
import asyncio
import json
import logging
import threading

import websockets
from obspy import UTCDateTime

import config
from sources import SSL_CONTEXT, _event

log = logging.getLogger("sismos")
URL = "wss://www.seismicportal.eu/standing_order/websocket"


def in_region(ev):
    r = config.REGION
    return r["minlat"] <= ev["lat"] <= r["maxlat"] and r["minlon"] <= ev["lon"] <= r["maxlon"]


class EmscStream:
    """Mantiene la conexión al websocket y un caché de los eventos recientes de la región."""

    def __init__(self, on_event, note=log.info):
        self.on_event = on_event  # on_event(ev, action) para eventos de la región
        self.note = note
        self.connected = False
        self.events = {}  # unid -> evento
        self.lock = threading.Lock()

    def start(self):
        threading.Thread(target=lambda: asyncio.run(self._run()), daemon=True).start()

    def search(self, start, end):
        with self.lock:
            return [e for e in self.events.values() if start <= e["time"] <= end]

    async def _run(self):
        delay = 5
        while True:
            try:
                async with websockets.connect(URL, open_timeout=20, ping_interval=60,
                                              ssl=SSL_CONTEXT) as ws:
                    self.connected = True
                    delay = 5
                    self.note("Conectado al websocket de EMSC")
                    async for raw in ws:
                        self._handle(raw)
            except Exception as e:
                if self.connected:
                    self.note(f"Websocket de EMSC desconectado: {e}")
            self.connected = False
            await asyncio.sleep(delay)
            delay = min(delay * 2, 300)

    def _handle(self, raw):
        try:
            msg = json.loads(raw)
            p = msg["data"]["properties"]
            ev = _event("EMSC", p["unid"], p["time"], p["lat"], p["lon"], p.get("depth"),
                        p.get("mag"), p.get("magtype"), p.get("flynn_region"), p.get("evtype"),
                        f"https://www.seismicportal.eu/eventdetails.html?unid={p['unid']}")
        except Exception as e:
            log.debug("Mensaje de EMSC no reconocido: %s", e)
            return
        if not in_region(ev):
            return
        with self.lock:
            self.events[ev["id"]] = ev
            # Guardar solo los últimos días
            old = UTCDateTime() - 3 * 86400
            self.events = {k: v for k, v in self.events.items() if v["time"] > old}
        self.on_event(ev, msg.get("action", "create"))
