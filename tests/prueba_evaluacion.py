"""Pruebas sin red de la evaluación (evaluacion/) y de su separación de la alerta.

Uso: python tests/prueba_evaluacion.py
"""
import ast
import json
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from obspy import UTCDateTime as T  # noqa: E402

import config  # noqa: E402
import decisiones  # noqa: E402
import intensidad  # noqa: E402
import sources  # noqa: E402
from evaluacion import metricas  # noqa: E402
from evaluacion.catalogo import emparejar  # noqa: E402
from evaluacion.repaso import con_disparos  # noqa: E402
from ubicador import Malla, TiemposP  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("ok    " if cond else "FALLA ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# La alerta (todo .py de la raíz) nunca importa la evaluación
for f in sorted(RAIZ.glob("*.py")):
    nombres = set()
    for nodo in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
        if isinstance(nodo, ast.Import):
            nombres |= {a.name.split(".")[0] for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            nombres.add(nodo.module.split(".")[0])
    check(f"{f.name} no importa evaluacion", "evaluacion" not in nombres)

# Intensidad
m, s = intensidad.mmi_prevista(7.7, 600)
check("Mw7,7 a 600 km: MMI prevista ~4", 3.5 < m < 5, f"{m:.2f}")
check("MMI prevista baja con la distancia",
      intensidad.mmi_prevista(5, 50)[0] > intensidad.mmi_prevista(5, 300)[0])
check("la incertidumbre de la magnitud agranda la sigma",
      intensidad.mmi_prevista(5, 100, 0.3)[1] > intensidad.mmi_prevista(5, 100)[1])
p = intensidad.prob_excedencia(3.0, 0.8, 3.0)
check("probabilidad de superar la MMI media = 0,5", abs(p - 0.5) < 1e-9, f"{p}")
# HEL midió PGV 0,30 cm/s en el Mw7,7 de Panamá (9-oct): MMI ~3
v = float(intensidad.mmi_observada(0.42, 0.30))
check("PGV 0,30 cm/s es MMI ~3", 2.8 < v < 3.2, f"{v:.2f}")
check("PGV de 10 cm/s es MMI ~6", 5.5 < float(intensidad.mmi_observada(None, 10)) < 6.5)

# Clasificación de Meier (2017), umbral MMI 4
t0 = T("2026-10-09T17:56:06")


def obs(mmi, cruces):
    return {"mmi": mmi, "ruido_mmi": 1.0, "cruces": {k: str(t0 + v) for k, v in cruces.items()}}


fuerte = obs(4.8, {"3.5": 50, "4.0": 60})
casi = obs(3.7, {"3.5": 55})
leve = obs(3.2, {})
c = metricas.clasificar
check("alerta a tiempo y MMI 4,8: acierto con 40 s de aviso",
      c(fuerte, t0 + 20, 4.0) == ("TP", 40, False), f"{c(fuerte, t0 + 20, 4.0)}")
check("alerta después del cruce: perdida (tarde)", c(fuerte, t0 + 70, 4.0) == ("FN", None, True))
check("sin alerta y MMI 4,8 (> 4 + 0,5): perdida", c(fuerte, None, 4.0)[0] == "FN")
check("alerta y MMI 3,7 (dentro de la tolerancia): acierto, aviso hasta el cruce de 3,5",
      c(casi, t0 + 20, 4.0) == ("TP", 35, False), f"{c(casi, t0 + 20, 4.0)}")
check("alerta y MMI 3,7 sin tolerancia: falsa", c(casi, t0 + 20, 4.0, tol=0)[0] == "FP")
check("alerta y MMI 3,2: falsa", c(leve, t0 + 20, 4.0)[0] == "FP")
check("sin alerta y MMI 4,3 (tolerada): correcta", c(obs(4.3, {"4.0": 60}), None, 4.0)[0] == "TN")
check("sitio sin medida y alerta: falsa", c(None, t0, 4.0)[0] == "FP")
check("ruido en la zona del umbral: no se juzga",
      c({"mmi": 4.0, "ruido_mmi": 3.6, "cruces": {}}, t0, 4.0) is None)
k = metricas.resumen([c(fuerte, t0 + 20, 4.0), c(fuerte, None, 4.0), c(leve, t0, 4.0),
                      c(leve, None, 4.0)])
check("pseudo-ROC: TPR = 0,5, FPR = 0,5, CAR = 0,5",
      (k["TPR"], k["FPR"], k["CAR"]) == (0.5, 0.5, 0.5), f"{k}")

# Registro de decisiones (el contrato) y repaso de disparos sintéticos
tp = TiemposP()
lat, lon, depth = 3.87, -75.63, 19  # Chaparral
picks = []
for s in ("HEL", "RUS", "OCA", "ARGC"):
    d = sources.distance_km(lat, lon, *config.STATIONS[s][3:5])
    picks.append((t0 + float(tp(d, depth)) + 3, s, 20.0))
lineas = con_disparos(sorted(picks), Malla(step=0.5))
check("el repaso da decisiones de los dos asociadores",
      {x["asociador"] for x in lineas} == {"ventana", "bayesiano"}, f"{lineas}")
check("las decisiones tienen el formato del contrato",
      all(x["v"] == decisiones.VERSION and x["origen"] == "repaso" and x["evento"] in
          ("nueva", "actualizacion") for x in lineas))
ev = {"source": "X", "id": "1", "time": t0, "lat": lat, "lon": lon, "depth": depth, "mag": 4.2}
check("la decisión se empareja con su sismo", emparejar(lineas[-1], [ev]) is ev)
with tempfile.TemporaryDirectory() as d:
    f = Path(d) / "decisiones.jsonl"
    det = {"id": "DET1", "level": "alta", "first_onset": t0, "stations": {},
           "magnitud": {"valor": 4.2, "n": 3},
           "medellin": {"mmi": 3.4, "sigma": 0.8, "prob": 0.6, "fuente": "magnitud",
                        "alerta": True, "alerta_desde": str(t0 + 30)}}
    decisiones.registrar(det, "nueva", t0 + 30, archivo=f)
    linea = json.loads(f.read_text(encoding="utf-8"))
    check("el servidor escribe una línea legible", linea["emitida"] == str(t0 + 30)
          and linea["magnitud"]["valor"] == 4.2 and linea["origen"] == "vivo"
          and linea["medellin"]["fuente"] == "magnitud", f"{linea}")

# Informe diario: aviso en Medellín y ΔMMI con el campo "medellin" del registro
import informe_diario  # noqa: E402
ms = [{"mmi": 2.5, "fuente": "magnitud", "alerta": False, "emitida": str(t0 + 20)},
      {"mmi": 3.4, "fuente": "plum-HEL", "alerta": True, "alerta_desde": str(t0 + 25),
       "umbral": 3.0, "emitida": str(t0 + 40),
       "observada": {"mmi": 3.2, "cruces": {"3.0": str(t0 + 38)}}}]
m = informe_diario.medellin_summary(ms)
check("el informe mide el aviso hasta el cruce del umbral en HEL",
      m["cruce"] - m["alerta"] == 13 and round(m["prevista"] - m["observada"], 1) == 0.2, f"{m}")

print()
if failures:
    print(f"{len(failures)} prueba(s) fallaron: {', '.join(failures)}")
    sys.exit(1)
print("Todas las pruebas pasaron.")
