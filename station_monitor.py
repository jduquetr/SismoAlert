"""Recepción de estaciones en observación, sin procesamiento para alertas."""
import threading
import time


class StationMonitor:
    def __init__(self, station):
        self.station = station
        self._lock = threading.Lock()
        self._last_packet = None
        self._last_sample = None

    def add(self, trace):
        if trace.stats.npts <= 0 or trace.stats.sampling_rate <= 0:
            return
        sample = float(trace.stats.endtime)
        with self._lock:
            self._last_packet = time.time()
            # Un paquete atrasado no hace retroceder la última muestra recibida.
            self._last_sample = max(sample, self._last_sample or sample)

    def status(self):
        with self._lock:
            packet, sample = self._last_packet, self._last_sample
        now = time.time()
        return {
            "station": self.station,
            "triggered": False,
            "peak_ratio": None,
            "latency_s": round(now - sample, 1) if sample is not None else None,
            "last_packet_age_s": round(now - packet, 1) if packet is not None else None,
        }
