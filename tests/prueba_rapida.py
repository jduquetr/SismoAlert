"""Pruebas rápidas sin red, para la revisión automática de GitHub (y para correr a mano).

Uso: python tests/prueba_rapida.py
Cubre lo que más fácil se rompe al cambiar el código: el modelo de tiempos de viaje, el
descarte de artefactos de la señal, el emparejamiento con catálogos y el guardado.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from obspy import UTCDateTime as T  # noqa: E402

import config  # noqa: E402
import server  # noqa: E402
import store  # noqa: E402
import traveltime  # noqa: E402
from detector import simultaneous_artifact  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("ok    " if cond else "FALLA ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# Tiempos de viaje: M4.3 de Istmina (27-sep), observados HEL +35 s, RUS +62 s, OCA +77 s
for sta, dist, obs in (("HEL", 232, 35.0), ("RUS", 431, 62.0), ("OCA", 562, 77.0)):
    tp = traveltime.p_time(dist, 43)
    check(f"P a {sta} cerca de lo observado", abs(obs - tp) <= 4, f"esperada {tp:.1f} s, observada {obs} s")
check("S llega después de P", traveltime.s_time(235, 43) > traveltime.p_time(235, 43))

# Artefacto: 9 estaciones en 11 s, de Providencia a Ecuador (detección del 29-sep 13:07)
t0 = T("2026-09-29T13:07:47")
art = {"stations": {s: {"onset": str(t0 + i), "ratio": 20.0}
                    for i, s in enumerate(["SMAR", "ARGC", "OCA", "PRV", "URI", "TUM", "OTAV", "CRJC", "RUS"])}}
check("señal simultánea se descarta", simultaneous_artifact(art) is not None)

# Sismo real: estaciones que se suman según la distancia (M3.8 del 25-sep 03:57)
t0 = T("2026-09-25T03:57:46")
real = {"stations": {s: {"onset": str(t0 + dt), "ratio": 20.0}
                     for s, dt in (("HEL", 0), ("RUS", 13), ("TUM", 18), ("OCA", 41), ("CRJC", 77), ("URI", 89))}}
check("sismo real no se descarta", simultaneous_artifact(real) is None)

# Emparejamiento: un M2.0 lejano y minutos antes no explica la detección de la noche del 28-sep
noche = {"first_onset": T("2026-09-28T03:55:02"), "stations": {
    "RUS": {"onset": "2026-09-28T03:55:02.318Z", "ratio": 9.2},
    "HEL": {"onset": "2026-09-28T03:55:25.048Z", "ratio": 10.2},
    "CRJC": {"onset": "2026-09-28T03:55:42.348Z", "ratio": 15.0}}}
m2 = dict(id="x", time=T("2026-09-28T03:52:33"), lat=3.85, lon=-75.64, depth=19.0, mag=2.0)
check("M2.0 lejano no se empareja", server.arrival_misfit(noche, m2) is None)

ist = {"first_onset": T("2026-09-27T21:57:36"), "stations": {
    "TUM": {"onset": "2026-09-27T21:57:36.3Z", "ratio": 8.5},   # ruido antes del sismo
    "HEL": {"onset": "2026-09-27T21:58:25.998Z", "ratio": 29.6},
    "RUS": {"onset": "2026-09-27T21:58:53.018Z", "ratio": 27.9}}}
m43 = dict(id="SGC2026tbmajr", time=T("2026-09-27T21:57:51"), lat=4.4648, lon=-76.6990, depth=43.0, mag=4.3)
check("Istmina se empareja pese al ruido previo", server.arrival_misfit(ist, m43) is not None)

# Guardado: escribir, recargar y volver a escribir (el error del 29-sep)
with tempfile.TemporaryDirectory() as tmp:
    store.DATA = Path(tmp)
    store.GEOJSON = Path(tmp) / "sismos-detectados.geojson"
    store._records = None
    det = dict(ist, id="DET-PRUEBA", detected_at=T("2026-09-27T21:58:38"), level="alta",
               catalog={"SGC": dict(m43, place="Istmina", status="manual", priority="informativa")})
    store.save(det)
    again = store.load_recent()
    store.save(dict(again[0], level="media"))
    fc = json.loads(store.GEOJSON.read_text(encoding="utf-8"))
    check("guardar, recargar y volver a guardar", fc["metadata"]["count"] == 1 and fc["features"][0]["geometry"])

check("config.USE_SGC existe", isinstance(config.USE_SGC, bool))

print()
if failures:
    print(f"{len(failures)} prueba(s) fallaron: {', '.join(failures)}")
    sys.exit(1)
print("Todas las pruebas pasaron")
