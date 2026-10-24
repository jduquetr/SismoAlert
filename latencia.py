"""Cuánto tardan los datos de cada estación en llegar al servidor.

Cada paquete de SeedLink trae la hora de su primera y su última muestra. La diferencia entre
la hora de llegada (reloj del servidor, sincronizado por NTP) y la de la última muestra es lo
que tardó en viajar desde la estación (SGC → EarthScope → servidor); la duración del paquete
es lo que la estación esperó para llenarlo. Una onda que llega a la estación al principio de
un paquete espera las dos cosas: ese es el retraso que se resta del tiempo de aviso.

Se resume por estación y por hora en datos/latencia.jsonl, una línea por estación:
{"hora", "estacion", "paquetes", "duracion_s" (mediana del paquete), "viaje_s" (mediana de
llegada − última muestra), "viaje_p90_s", "viaje_max_s", "retraso_s" (mediana de llegada −
primera muestra: el peor caso de cada paquete)}.
"""
import json
import logging
import threading

import numpy as np

import store

log = logging.getLogger("latencia")

ARCHIVO = store.DATA / "latencia.jsonl"


class Latencia:
    def __init__(self, archivo=ARCHIVO, periodo_s=3600):
        self.archivo = archivo
        self.periodo_s = periodo_s
        self.lock = threading.Lock()
        self.hora = None  # inicio del periodo en curso (s desde 1970)
        self.datos = {}   # estación -> [(duración, viaje)]

    def paquete(self, estacion, inicio, fin, llegada):
        """Anota un paquete: horas (s desde 1970) de su primera y última muestra y de llegada."""
        periodo = llegada - llegada % self.periodo_s
        with self.lock:
            if self.hora is not None and periodo != self.hora:
                self._guardar()
            self.hora = periodo
            self.datos.setdefault(estacion, []).append((fin - inicio, llegada - fin))

    def _guardar(self):
        from obspy import UTCDateTime
        lineas = []
        for sta, v in sorted(self.datos.items()):
            dur, viaje = np.array(v).T
            lineas.append({"hora": str(UTCDateTime(self.hora)), "estacion": sta,
                           "paquetes": len(v), "duracion_s": round(float(np.median(dur)), 2),
                           "viaje_s": round(float(np.median(viaje)), 2),
                           "viaje_p90_s": round(float(np.percentile(viaje, 90)), 2),
                           "viaje_max_s": round(float(viaje.max()), 2),
                           "retraso_s": round(float(np.median(dur + viaje)), 2)})
        self.datos = {}
        try:
            self.archivo.parent.mkdir(parents=True, exist_ok=True)
            with open(self.archivo, "a", encoding="utf-8") as f:
                for x in lineas:
                    f.write(json.dumps(x) + "\n")
        except OSError:
            log.exception("No se pudo guardar la latencia")
