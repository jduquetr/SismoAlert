"""Magnitud preliminar a partir de la amplitud máxima medida en cada estación.

Como en el sistema de Japón (Tamaribuchi et al., 2014; Kodera et al., 2021), cada estación
da una magnitud con su amplitud máxima A y su distancia hipocentral R,

    M = a·log10(A) + b·log10(R) + c + corrección de la estación,

y la del sismo es la mediana de las más cercanas al epicentro (config.MAGNITUD_*).

La amplitud es, como en la JMA, la del desplazamiento (banda MAGNITUD_BANDA_DESP_HZ): la
velocidad en la banda del detector (2-10 Hz) se satura y daba M5,1 para el Mw7,7 de Panamá
del 9-oct. Si el desplazamiento no supera MAGNITUD_SNR_MIN veces el ruido (sismos pequeños),
se usa la velocidad, también como en la JMA.

Los coeficientes salen de calibrar con sismos de catálogo registrados por nuestras
estaciones (tools/calibrar_magnitud.py -> magnitud.json). Hay unos para los primeros 5 s
desde el disparo y otros para 30 s: mientras no pasan 30 s se usa la ventana de 5 s, y la
magnitud sube a medida que llega la parte fuerte de la señal.

Es una estimación gruesa (±0,3-0,4, y por debajo en sismos de M6 o más): sirve para ordenar
alertas, no para informar.
"""
import json
from pathlib import Path

import numpy as np

import config
from ubicador import _distance_km

HERE = Path(__file__).parent
TIPOS = ("desp", "vel")  # en orden de preferencia


def senal(tr, tipo):
    """Valor absoluto de la señal filtrada (cuentas; en "desp", cuentas·s), solo hacia atrás
    en el tiempo, como en vivo. tr: traza cruda; no se modifica."""
    v = tr.copy()
    v.data = v.data.astype(float)
    v.detrend("demean")
    v.taper(0.02, side="left")
    nyq = 0.4 * v.stats.sampling_rate
    if tipo == "vel":
        v.filter("bandpass", freqmin=config.BANDPASS[0], freqmax=min(config.BANDPASS[1], nyq),
                 corners=4, zerophase=False)
    else:
        f1, f2 = config.MAGNITUD_BANDA_DESP_HZ
        v.filter("bandpass", freqmin=f1, freqmax=min(f2, nyq), corners=4, zerophase=False)
        v.integrate()
        v.filter("highpass", freq=f1, corners=2, zerophase=False)
    return np.abs(v.data)


def medir(tr, onset, ventanas=None):
    """Amplitudes máximas tras el disparo y ruido antes de él, para cada tipo de señal.

    Devuelve {"desp": {ventana: máx}, "vel": {...}, "ruido": {"desp": máx, "vel": máx}}.
    Las ventanas que aún no terminaron llevan el máximo hasta ahora.
    """
    ventanas = ventanas or config.MAGNITUD_VENTANAS_S
    df = tr.stats.sampling_rate
    i0 = int(round((onset - tr.stats.starttime) * df))
    out = {"ruido": {}}
    for tipo in TIPOS:
        a = senal(tr, tipo)
        out["ruido"][tipo] = float(a[max(0, i0 - int(25 * df)):max(1, i0 - int(2 * df))].max())
        out[tipo] = {w: float(a[i0:i0 + int(w * df) + 1].max()) for w in ventanas
                     if i0 < len(a)}
    return out


class Magnitud:
    def __init__(self, path=HERE / "magnitud.json"):
        path = Path(path)
        self.ok = path.exists()
        if not self.ok:
            return
        t = json.loads(path.read_text(encoding="utf-8"))
        self.sens = t["sensibilidad"]
        self.coef = {tipo: {int(w): k for w, k in v.items()} for tipo, v in t["tipos"].items()}

    def tipo(self, amps, w):
        """El desplazamiento si se distingue del ruido; si no, la velocidad."""
        for tipo in TIPOS:
            if amps.get(tipo, {}).get(w, 0) >= config.MAGNITUD_SNR_MIN * amps["ruido"][tipo] > 0:
                return tipo
        return "vel"

    def estacion(self, sta, amps, w, r_km):
        """(magnitud, sigma) de una estación en la ventana w, o None."""
        tipo = self.tipo(amps, w)
        k = self.coef.get(tipo, {}).get(w)
        a = amps.get(tipo, {}).get(w, 0)
        if k is None or sta not in self.sens or a <= 0:
            return None
        m = (k["a"] * np.log10(a / self.sens[sta]) + k["b"] * np.log10(max(r_km, 1.0)) + k["c"]
             + k["correccion"].get(sta, 0.0))
        return float(m), k["sigma"]

    def estimar(self, amps, loc, now):
        """Magnitud del sismo.

        amps: {estación: (hora del disparo, medir(...))}. loc: algo con lat, lon y depth.
        now: hora actual, para saber qué ventanas ya terminaron.
        Devuelve {"valor", "n", "incertidumbre", "estaciones": {estación: M}} o None.
        """
        if not self.ok or not amps:
            return None
        dist = {}
        for sta, (onset, a) in amps.items():
            if sta in config.STATIONS and a:
                lat, lon = config.STATIONS[sta][3:5]
                dist[sta] = float(_distance_km(loc.lat, loc.lon, lat, lon))
        if not dist:
            return None
        nearest = min(dist.values())
        cerca = sorted((d, s) for s, d in dist.items()
                       if d <= min(nearest + config.MAGNITUD_MARGEN_KM, config.MAGNITUD_MAX_KM))
        ms, sig = {}, []
        for d, sta in cerca[:config.MAGNITUD_ESTACIONES]:
            onset, a = amps[sta]
            ventanas = sorted(a.get("vel", {}))
            if not ventanas:
                continue
            done = [w for w in ventanas if now - onset >= w]
            w = max(done) if done else ventanas[0]
            r = self.estacion(sta, a, w, float(np.hypot(d, loc.depth)))
            if r is not None:
                ms[sta] = round(r[0], 1)
                sig.append(r[1])
        if not ms:
            return None
        # Desviación de una estación (de la calibración) reducida por el número de estaciones
        return {"valor": round(float(np.median(list(ms.values()))), 1), "n": len(ms),
                "incertidumbre": round(float(np.mean(sig) / np.sqrt(len(ms))), 2),
                "estaciones": ms}
