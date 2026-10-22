"""Pruebas sin red del ubicador y el asociador bayesianos (rama Japon).

Uso: python tests/prueba_japon.py
Con sismos sintéticos: los disparos son la P de IASP91 más un retraso como el de nuestros
disparos STA/LTA. Usa una malla gruesa (0,5°) para que corra en segundos.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from obspy import UTCDateTime as T  # noqa: E402

import config  # noqa: E402
import sources  # noqa: E402
from asociador import BayesAssociator  # noqa: E402
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

print()
if failures:
    print(f"{len(failures)} prueba(s) fallaron: {', '.join(failures)}")
    sys.exit(1)
print("Todas las pruebas pasaron.")
