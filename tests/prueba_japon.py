"""Pruebas sin red del ubicador y el asociador bayesianos (rama Japon).

Uso: python tests/prueba_japon.py
Con sismos sintéticos: los disparos son la P de IASP91 más un retraso como el de nuestros
disparos STA/LTA. Usa una malla gruesa (0,5°) para que corra en segundos.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from obspy import Trace  # noqa: E402
from obspy import UTCDateTime as T  # noqa: E402

import config  # noqa: E402
import sources  # noqa: E402
from asociador import BayesAssociator  # noqa: E402
from detector import StationTrigger  # noqa: E402
from magnitud import Magnitud  # noqa: E402
from ubicador import Malla, TiemposP, ubicar  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("ok    " if cond else "FALLA ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


tp = TiemposP()
malla = Malla(step=0.5)


def synthetic(lat, lon, depth, origin, stations, delay=3.0):
    """Disparos que daría un sismo en (lat, lon, depth) en esas estaciones."""
    out = {}
    for s in stations:
        d = sources.distance_km(lat, lon, *config.STATIONS[s][3:5])
        out[s] = origin + float(tp(d, depth)) + delay
    return out


# Tiempos de viaje: el modelo de dos capas daba 5 s para la P de un sismo a 150 km bajo
# la estación; IASP91 da ~20 s. Y a 1.000 km llega antes desde 150 km que desde 10 km.
check("P desde 150 km de profundidad, justo encima", 18 <= float(tp(0, 150)) <= 22, f"{float(tp(0, 150)):.1f} s")
check("P a 1.000 km llega antes desde 150 km que desde 10 km", float(tp(1000, 150)) < float(tp(1000, 10)))
check("tiempos crecen con la distancia", float(tp(100, 10)) < float(tp(300, 10)) < float(tp(600, 10)))

# Ubicación: sismo en Chaparral (Tolima), como los del 25-sep, con 6 estaciones
t0 = T("2026-09-25T00:37:16")
quake = (3.7, -75.5, 15)
picks = synthetic(*quake, t0, ["HEL", "RUS", "TUM", "OCA", "CRJC", "URI"])
loc = ubicar(malla, picks, max(picks.values()) + 5)
err = sources.distance_km(loc.lat, loc.lon, quake[0], quake[1])
check("ubica el sismo de Chaparral a menos de 100 km", err < 100, f"error {err:.0f} km")
check("la hora de origen sale cerca (con el retraso de los disparos)",
      abs(loc.origin - (t0 + 3)) < 8, f"{loc.origin - t0:+.1f} s")

# Un disparo ajeno no arrastra la solución
noisy = dict(picks, PRV=t0 + 20)
loc2 = ubicar(malla, noisy, max(noisy.values()) + 5)
err2 = sources.distance_km(loc2.lat, loc2.lon, quake[0], quake[1])
check("con un disparo de ruido en PRV sigue a menos de 150 km", err2 < 150, f"error {err2:.0f} km")
check("y el disparo de PRV no encaja", "PRV" not in loc2.fits(), f"residuos {loc2.residuals}")


def replay(events):
    """Pasa disparos (estación, hora, sta/lta) por el asociador; devuelve las detecciones."""
    dets = {}
    now = {"t": None}
    a = BayesAssociator(on_detection=lambda d: dets.__setitem__(d["id"], d),
                        on_update=lambda d: dets.__setitem__(d["id"], d),
                        malla=malla, clock=lambda: now["t"])
    for t, s, r in sorted(events, key=lambda x: x[0]):
        now["t"] = t
        a.trigger(s, t, r)
    return list(dets.values())


# Sismo de Chaparral con un disparo de ruido en PRV en medio: una sola detección, sin PRV
ev = [(t, s, 20.0) for s, t in picks.items()] + [(t0 + 40, "PRV", 15.0)]
dets = replay(ev)
check("Chaparral + ruido en PRV: una detección", len(dets) == 1, f"{len(dets)} detecciones")
if dets:
    check("el ruido de PRV queda fuera de la detección", "PRV" not in dets[0]["stations"],
          f"estaciones {list(dets[0]['stations'])}")
    check("nivel alta: HEL registró el sismo", dets[0]["level"] == "alta", dets[0]["level"])

# Dos sismos casi simultáneos: Chaparral y, 15 s después, uno en La Guajira que dispara las
# estaciones del norte. La ventana de 120 s los juntaría en uno.
guajira = synthetic(11.3, -72.5, 20, t0 + 15, ["CRJC", "URI", "SMAR"])
ev = ([(t, s, 20.0) for s, t in picks.items() if s not in ("CRJC", "URI")]
      + [(t, s, 20.0) for s, t in guajira.items()])
dets = replay(ev)
north = [d for d in dets if set(d["stations"]) >= {"CRJC", "URI", "SMAR"}]
check("Chaparral + Guajira simultáneos: dos detecciones", len(dets) == 2,
      f"{[list(d['stations']) for d in dets]}")
check("las estaciones del norte quedan juntas en la de La Guajira",
      len(north) == 1 and "HEL" not in north[0]["stations"], f"{[list(d['stations']) for d in dets]}")

# Dos disparos sueltos a 1.500 km (OTAV y PRV, 28-sep): no es detección
dets = replay([(t0, "OTAV", 9.0), (t0 + 57, "PRV", 9.0)])
check("OTAV y PRV sueltos no dan detección", not dets, f"{len(dets)} detecciones")

# Intensidad (evaluación al estilo de Meier, 2017)
import intensidad  # noqa: E402

m, s = intensidad.mmi_prevista(7.7, 600)
check("Mw7,7 a 600 km: MMI prevista ~4", 3.5 < m < 5, f"{m:.2f}")
check("MMI prevista baja con la distancia",
      intensidad.mmi_prevista(5, 50)[0] > intensidad.mmi_prevista(5, 300)[0])
p = intensidad.prob_excedencia(3.0, 0.8, 3.0)
check("probabilidad de superar la MMI media = 0,5", abs(p - 0.5) < 1e-9, f"{p}")
# HEL midió PGV 0,30 cm/s en el Mw7,7 de Panamá (9-oct): MMI ~3
v = float(intensidad.mmi_observada(0.42, 0.30))
check("PGV 0,30 cm/s es MMI ~3", 2.8 < v < 3.2, f"{v:.2f}")
check("PGV de 10 cm/s es MMI ~6", 5.5 < float(intensidad.mmi_observada(None, 10)) < 6.5)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from evaluar_alertas import clasificar  # noqa: E402

ev = [{"source": "X", "id": str(i)} for i in range(4)]
obs = {"X:0": {"ruido_mmi": 1, "cruces": {"3.0": str(t0 + 60)}},   # sentido, aviso a tiempo
       "X:1": {"ruido_mmi": 1, "cruces": {"3.0": str(t0 + 60)}},   # sentido, aviso tarde
       "X:2": {"ruido_mmi": 1, "cruces": {"3.0": None}},           # no sentido, con aviso
       "X:3": {"ruido_mmi": 1, "cruces": {"3.0": str(t0 + 60)}}}   # sentido, sin aviso
hora = {"0": t0 + 20, "1": t0 + 90, "2": t0 + 10, "3": None}
k = clasificar(ev, obs, lambda e: hora[e["id"]], 3.0, falsas_sin_sismo=2)
check("clasificación TP/tarde/FP/FN",
      (k["TP"], k["tarde"], k["FP"], k["FN"], k["TN"]) == (1, 1, 3, 1, 0), f"{k}")
check("tiempo de aviso del acierto", k["aviso_s"][0] == 40, f"{k['aviso_s']}")

# Magnitud preliminar, con coeficientes inventados (los reales salen de calibrar):
# M = log10(A) + 1,5·log10(R) + 6
K = {"a": 1.0, "b": 1.5, "c": 6.0, "sigma": 0.3, "correccion": {}}
mag = Magnitud.__new__(Magnitud)
mag.ok, mag.sens = True, {s: 1e9 for s in config.STATIONS}
mag.coef = {t: {5: K, 30: K} for t in ("desp", "vel")}


def amps_for(m, sta, q=quake, ruido=1.0):
    """Amplitudes (cuentas) que daría un sismo de magnitud m en (q) en la estación sta."""
    d = sources.distance_km(q[0], q[1], *config.STATIONS[sta][3:5])
    a = 10 ** (m - K["c"] - K["b"] * math.log10(math.hypot(d, q[2]))) * 1e9
    return {"desp": {5: a, 30: a}, "vel": {5: a, 30: a}, "ruido": {"desp": ruido, "vel": ruido}}


class _Loc:
    lat, lon, depth = quake


amps = {s: (t, amps_for(4.5, s)) for s, t in picks.items()}
m = mag.estimar(amps, _Loc, max(picks.values()) + 40)
check("magnitud de un M4,5 sintético", m and abs(m["valor"] - 4.5) < 0.05, m)
amps["PRV"] = (t0 + 60, amps_for(7.0, "PRV"))
m = mag.estimar(amps, _Loc, max(picks.values()) + 40)
check("una estación a más de 700 km no cuenta (Torishima, 2020)",
      m and "PRV" not in m["estaciones"] and abs(m["valor"] - 4.5) < 0.05, m)
near = min(picks, key=lambda s: sources.distance_km(quake[0], quake[1], *config.STATIONS[s][3:5]))
far = {s for s in picks if sources.distance_km(quake[0], quake[1], *config.STATIONS[s][3:5])
       > sources.distance_km(quake[0], quake[1], *config.STATIONS[near][3:5]) + 150}
check("tampoco las que están más de 150 km más lejos que la más cercana",
      m and not far & set(m["estaciones"]), f"{m} lejanas {far}")
a = amps_for(4.5, "HEL", ruido=1e12)
a["ruido"]["vel"] = 1.0
check("si el desplazamiento no supera el ruido se usa la velocidad", mag.tipo(a, 30) == "vel")

# El detector mide las amplitudes de los primeros 5 y 30 s del disparo
trig = StationTrigger("HEL")
rng = np.random.default_rng(0)
data = rng.normal(0, 10, 100 * 90)
data[100 * 60:100 * 62] += 3000 * np.sin(2 * np.pi * 5 * np.arange(200) / 100)  # P
data[100 * 70:100 * 75] += 9000 * np.sin(2 * np.pi * 4 * np.arange(500) / 100)  # S, 10 s después
tr = Trace(data.astype(np.int32), header={"station": "HEL", "sampling_rate": 100.0,
                                          "starttime": t0})
onsets = [trig.add(tr.slice(t0 + i, t0 + i + 1 - 0.01)) for i in range(90)]
check("dispara en la P", any(onsets) and abs([o for o in onsets if o][0] - (t0 + 60)) < 1)
v = trig.amps.get("vel", {})
check("velocidad de 5 s: la P; de 30 s: la S", 2000 < v.get(5, 0) < 4000 and v.get(30, 0) > 6000,
      trig.amps)
check("la señal supera bien el ruido de antes del disparo",
      v.get(5, 0) > 20 * trig.amps.get("ruido", {}).get("vel", 1e9), trig.amps)

print()
if failures:
    print(f"{len(failures)} prueba(s) fallaron: {', '.join(failures)}")
    sys.exit(1)
print("Todas las pruebas pasaron.")
