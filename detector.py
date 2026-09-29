"""Detección STA/LTA por estación y asociación entre estaciones."""
import threading
import time

from obspy import Stream, UTCDateTime
from obspy.signal.trigger import classic_sta_lta

import config


class StationTrigger:
    """Mantiene un búfer de señal de una estación y detecta inicios de sismo."""

    def __init__(self, station):
        self.station = station
        self.stream = Stream()
        self.triggered = False
        self.onset = None
        self.peak_ratio = 0.0
        self.off_since = None     # cuándo bajó del umbral (para el tiempo muerto)
        self.last_checked = None  # último instante ya evaluado
        self.last_packet = None   # hora de llegada del último paquete (reloj local)
        self.last_sample = None   # hora del último dato (UTCDateTime)

    def reset(self):
        """Descarta la señal acumulada; el STA/LTA se vuelve a estabilizar (~35 s)."""
        self.stream = Stream()
        self.triggered = False
        self.onset = None
        self.peak_ratio = 0.0
        self.off_since = None
        self.last_checked = None

    def add(self, trace):
        """Agrega un trozo de señal. Devuelve la hora de inicio si hay un disparo nuevo."""
        self.last_packet = time.time()
        if len(self.stream):
            gap = trace.stats.starttime - self.stream[0].stats.endtime
            if gap > config.GAP_RESET_S:
                # Un hueco (reconexión, corte de red, PC suspendido) no se rellena: unir la
                # señal a través de él produce un salto que dispara con STA/LTA ~30 en todas
                # las estaciones a la vez. Se empieza de cero.
                self.reset()
        self.stream += trace
        self.stream.merge(method=1, fill_value="interpolate")
        tr = self.stream[0]
        tr.stats.processing = []
        self.last_sample = tr.stats.endtime
        tr.trim(tr.stats.endtime - config.BUFFER_S)
        return self._evaluate()

    def _evaluate(self):
        tr = self.stream[0].copy()
        df = tr.stats.sampling_rate
        nlta = int(config.LTA_S * df)
        if tr.stats.npts < nlta + int(5 * df):
            return None
        tr.detrend("demean")
        tr.taper(0.02, side="left")
        # Estaciones con muestreo bajo (p. ej. BHZ a 20 Hz) no admiten el tope de 10 Hz
        fmax = min(config.BANDPASS[1], 0.4 * df)
        tr.filter("bandpass", freqmin=config.BANDPASS[0], freqmax=fmax, corners=4, zerophase=False)
        cft = classic_sta_lta(tr.data, int(config.STA_S * df), nlta)
        start = tr.stats.starttime
        # Solo evaluar muestras nuevas y con el LTA ya estable
        first = nlta
        if self.last_checked is not None:
            first = max(first, int((self.last_checked - start) * df) + 1)
        self.last_checked = tr.stats.endtime
        new_onset = None
        for i in range(first, len(cft)):
            v = cft[i]
            t = start + i / df
            if not self.triggered:
                dead = self.off_since is not None and t - self.off_since < config.DEAD_TIME_S
                if v >= config.THR_ON and not dead:
                    self.triggered = True
                    self.onset = t
                    self.peak_ratio = v
                    new_onset = t
            else:
                self.peak_ratio = max(self.peak_ratio, v)
                if v <= config.THR_OFF:
                    self.triggered = False
                    self.off_since = t
        return new_onset

    def status(self):
        return {
            "station": self.station,
            "triggered": self.triggered,
            "peak_ratio": round(float(self.peak_ratio), 1) if self.triggered else None,
            "latency_s": (round(UTCDateTime() - self.last_sample, 1)
                          if self.last_sample else None),
            "last_packet_age_s": (round(time.time() - self.last_packet, 1)
                                  if self.last_packet else None),
        }


def simultaneous_artifact(det):
    """Motivo si la detección parece un artefacto de la señal y no un sismo, si no None.

    Un sismo de la región no llega casi a la vez a estaciones separadas por cientos de km:
    la onda más rápida (Pn, 8 km/s) tarda más de 100 s en recorrer 800 km, así que las
    estaciones se van sumando de a poco. Cuando un bloque de 6 o más estaciones dispara
    fuerte dentro de 20 s y en él hay pares a más de 800 km, la causa es la señal misma
    (un hueco al reconectar, un corte de red), no un sismo. Se busca el bloque y no todo
    el rango porque un disparo de ruido suelto puede estirar la ventana.
    """
    import math
    strong = sorted((UTCDateTime(v["onset"]), s) for s, v in det.get("stations", {}).items()
                    if v["ratio"] >= config.MIN_RATIO and s in config.STATIONS)
    best = []
    for i, (t_i, _) in enumerate(strong):
        block = [(t, s) for t, s in strong[i:] if t - t_i <= 20]
        if len(block) > len(best):
            best = block
    if len(best) < 6:
        return None
    pos = [config.STATIONS[s][3:5] for _, s in best]
    far = max(111.2 * math.dist(a, b) for a in pos for b in pos)
    if far < 800:
        return None
    span = best[-1][0] - best[0][0]
    return (f"{len(best)} estaciones dispararon en {span:.0f} s estando hasta a {far:.0f} km entre "
            "sí; un sismo de la región no llega tan rápido. Probable hueco en la señal "
            "(reconexión o corte de red).")


def n_groups(stations):
    """Cuenta confirmaciones independientes (las estaciones agrupadas valen por una)."""
    return len({config.STATION_GROUPS.get(s, s) for s in stations})


class Associator:
    """Agrupa disparos cercanos en el tiempo y decide cuándo hay una detección."""

    def __init__(self, on_detection, on_update):
        self.on_detection = on_detection  # detección nueva
        self.on_update = on_update        # cambia el nivel o se suman estaciones
        self.lock = threading.Lock()
        self.pending = {}  # estación -> {"onset": UTCDateTime, "ratio": float}
        self.current = None

    def trigger(self, station, onset, ratio):
        """Una estación acaba de dispararse."""
        with self.lock:
            cur = self.current
            if cur and onset - cur["first_onset"] <= config.ASSOC_WINDOW_S:
                if station not in cur["stations"]:
                    cur["stations"][station] = {"onset": str(onset), "ratio": round(float(ratio), 1)}
                    self._refresh(cur)
                return
            self.pending = {s: p for s, p in self.pending.items()
                            if onset - p["onset"] <= config.ASSOC_WINDOW_S}
            self.pending.setdefault(station, {"onset": onset, "ratio": float(ratio)})
            self._check_pending()

    def peak(self, station, ratio):
        """Actualiza la relación STA/LTA máxima de una estación disparada."""
        with self.lock:
            cur = self.current
            if cur and station in cur["stations"]:
                old = cur["stations"][station]["ratio"]
                if ratio > old + 0.5:
                    cur["stations"][station]["ratio"] = round(float(ratio), 1)
                    self._refresh(cur, quiet=True)
            elif station in self.pending:
                self.pending[station]["ratio"] = max(self.pending[station]["ratio"], float(ratio))
                self._check_pending()

    def _check_pending(self):
        local = self.pending.get(config.LOCAL_STATION)
        local_strong = (config.ALERT_LOCAL_ONLY and local is not None
                        and local["ratio"] >= config.LOCAL_ONLY_MIN_RATIO)
        strong = [s for s, p in self.pending.items() if p["ratio"] >= config.MIN_RATIO]
        needed = (config.MIN_STATIONS if config.LOCAL_STATION in strong
                  else config.MIN_STATIONS_REMOTE)
        if n_groups(strong) >= needed or local_strong:
            # La ventana arranca en el primer disparo fuerte; los débiles solo acompañan
            anchors = strong or [config.LOCAL_STATION]
            first = min(self.pending[s]["onset"] for s in anchors)
            det = {
                "id": f"DET{first.strftime('%Y%m%d%H%M%S')}",
                "first_onset": first,
                "detected_at": UTCDateTime(),
                "stations": {s: {"onset": str(p["onset"]), "ratio": round(p["ratio"], 1)}
                             for s, p in self.pending.items()},
            }
            self._set_level(det)
            self.current = det
            self.pending = {}
            self.on_detection(det)

    def _refresh(self, det, quiet=False):
        old = det.get("level")
        self._set_level(det)
        if not quiet or det["level"] != old:
            self.on_update(det)

    @staticmethod
    def _set_level(det):
        sts = {s: p for s, p in det["stations"].items() if p["ratio"] >= config.MIN_RATIO}
        n = len(sts)
        if n_groups(sts) >= config.MIN_STATIONS and config.LOCAL_STATION in sts:
            det["level"] = "alta"
            det["message"] = (f"Sismo detectado en {n} estaciones, incluida HEL (Medellín): "
                              "probablemente se sintió en Medellín")
        elif n_groups(sts) >= config.MIN_STATIONS_REMOTE:
            det["level"] = "media"
            det["message"] = f"Sismo detectado en {n} estaciones de Colombia y vecinos"
        else:
            det["level"] = "baja"
            det["message"] = ("Movimiento fuerte en HEL (Medellín), aún sin confirmación "
                              "de otras estaciones")
