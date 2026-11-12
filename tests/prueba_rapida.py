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


# Tiempos de viaje: M4.3 de Istmina (27-sep), observados HEL +35 s, RUS +62 s, OCA +77 s. Los
# disparos STA/LTA llegan ~3 s tarde frente a IASP91 (registro de la VM): se admite de -1 a +7 s
for sta, dist, obs in (("HEL", 232, 35.0), ("RUS", 431, 62.0), ("OCA", 562, 77.0)):
    tp = traveltime.p_time(dist, 43)
    check(f"P a {sta} cerca de lo observado", -1 <= obs - tp <= 7, f"esperada {tp:.1f} s, observada {obs} s")
check("S llega después de P", traveltime.s_time(235, 43) > traveltime.p_time(235, 43))
# Sismo del nido de Bucaramanga (150 km): la P tarda ~20 s en subir al epicentro (el modelo de
# dos capas de antes daba 5 s)
check("P de un sismo profundo depende de la profundidad", 19 <= traveltime.p_time(0, 150) <= 21,
      f"{traveltime.p_time(0, 150):.1f} s")
check("tiempos más allá de la tabla crecen", traveltime.p_time(5000, 10) > traveltime.p_time(4000, 10))

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

# Intensidad en Medellín: corrección calibrada en HEL (intensidad_medellin.json), distinta para
# sismos someros e intermedios, y más baja que AWW12 sin corregir para el M4,6 de Bello de 2024
# (AWW12 daba 4,7; HEL midió 2,4)
import intensidad  # noqa: E402
import prevision  # noqa: E402

check("hay corrección de intensidad para Medellín", intensidad.CORRECCION_MEDELLIN is not None)
bello = intensidad.mmi_medellin(4.6, 24, 18)[0]
check("la corrección baja el sismo de Bello", bello < intensidad.mmi_aww12(4.6, 24), f"{bello:.1f}")
check("la corrección depende de la profundidad",
      intensidad.mmi_medellin(5.5, 300, 150)[0] != intensidad.mmi_medellin(5.5, 300, 20)[0])
check("la incertidumbre de la magnitud solo agranda la sigma",
      intensidad.mmi_medellin(5, 200, 30, 0.4)[0] == intensidad.mmi_medellin(5, 200, 30)[0]
      and intensidad.mmi_medellin(5, 200, 30, 0.4)[1] > intensidad.mmi_medellin(5, 200, 30)[1])
check("HEL en la evaluación no lleva el término de sitio de la ciudad",
      intensidad.mmi_sitio(config.LOCAL_STATION, 5, 200, 30)[0]
      == intensidad.mmi_medellin(5, 200, 30)[0] - config.INTENSIDAD_SITIO_MEDELLIN)


# Umbral por fuente: la magnitud alerta con su probabilidad calibrada; PLUM no se rebaja
class _Loc:
    lat, lon, depth = 6.8, -73.1, 150  # nido de Bucaramanga


ahora = T("2026-11-12T00:01:00")
picks = {"RUS": {"onset": T("2026-11-12T00:00:00"), "amps": {}}}
r = (prevision._km_a_medellin(_Loc.lat, _Loc.lon) ** 2 + _Loc.depth ** 2) ** 0.5
m_lim = next(m / 10 for m in range(30, 80) if intensidad.prob_excedencia(
    *intensidad.mmi_medellin(m / 10, r, _Loc.depth, 0.3), config.ALERTA_MMI)
    >= config.ALERTA_PROB_MAGNITUD)
mag = {"valor": m_lim, "incertidumbre": 0.3, "estaciones": {"RUS": m_lim}, "n": 1}
check("la magnitud alerta al llegar a ALERTA_PROB_MAGNITUD",
      prevision.medellin(picks, _Loc, mag, ahora)["alerta"], f"M{m_lim}")
mag["valor"] = mag["estaciones"]["RUS"] = round(m_lim - 0.3, 1)
check("y no por debajo", not prevision.medellin(picks, _Loc, mag, ahora)["alerta"])
check("PLUM mantiene ALERTA_PROB", prevision.prob_minima("plum-HEL") == config.ALERTA_PROB)


# Nube de epicentros (apagada en config, se prueba el cálculo): dos nodos, la media queda entre
# los dos y la sigma crece
class _Malla:
    import numpy as _np
    lat, lon, depth = _np.array([6.25, 6.8]), _np.array([-75.0, -73.1]), _np.array([30.0, 150.0])


class _Nube:
    malla, idx, w = _Malla, [0, 1], [0.5, 0.5]


mmi_n, sig_n = prevision._nube(_Nube, [5.0, 5.0], 0.0, 0.3)
a0 = intensidad.mmi_medellin(5.0, (prevision._km_a_medellin(6.25, -75.0) ** 2 + 900) ** 0.5, 30, 0.3)
check("la nube de epicentros agranda la sigma", sig_n > a0[1], f"{sig_n:.2f}")

print()
if failures:
    print(f"{len(failures)} prueba(s) fallaron: {', '.join(failures)}")
    sys.exit(1)
print("Todas las pruebas pasaron")
