"""Métricas de Meier (2017) para juzgar alertas por sitio.

Meier, M.-A. (2017). How "good" are real-time ground motion predictions from Earthquake
Early Warning systems? J. Geophys. Res. Solid Earth 122, 5561-5577. doi:10.1002/2017JB014025

- Una alerta no se puede cancelar: cuenta desde la primera vez que se cumple el criterio.
- Tiempo de aviso: desde la alerta hasta que el sitio supera el umbral (no hasta la onda S).
- Clasificación con tolerancia (sección 4.3, ±0,5 MMI): acierto (TP) si hubo alerta a tiempo
  y el sitio llegó al menos a umbral − tol; falsa (FP) si hubo alerta y quedó más de tol por
  debajo; perdida (FN) si superó umbral + tol sin alerta a tiempo (sin alerta o tarde);
  el resto, correcta sin alerta (TN). Con tol = 0 son los límites estrictos.
- Los TN dependen de qué sismos se escojan (con sitios lejanos subirían sin mejorar nada), así
  que se resume con el "pseudo-ROC" normalizado por TP + FN: TPR = TP/(TP+FN) y
  FPR = FP/(TP+FN), y con la tasa de alertas correctas CAR = TP/(TP+FP).
- Error de predicción en función del tiempo de aviso: ΔMMI = observada − predicha, en cada
  momento en que había predicción, frente al tiempo que faltaba para el cruce de referencia.
"""
import statistics

from obspy import UTCDateTime


def clasificar(obs, t_alerta, umbral, tol=0.5):
    """Clase de un sitio para un sismo: ("TP"|"FP"|"FN"|"TN", aviso_s, tarde) o None.

    obs: medida del sitio (observado.py) o None si el sitio no la tiene, que se toma como
    no sentido. t_alerta: hora de la alerta para ese sitio o None.
    """
    if obs is None:
        obs = {"mmi": 1.0, "ruido_mmi": 0.0, "cruces": {}}
    if obs["ruido_mmi"] >= umbral - tol:
        return None  # el ruido del sitio ya estaba en la zona del umbral: no se puede juzgar
    mmi = obs["mmi"]
    nivel = umbral if mmi >= umbral else umbral - tol
    cruce = obs["cruces"].get(f"{nivel:.1f}")
    cruce = UTCDateTime(cruce) if cruce else None
    if t_alerta is not None and mmi >= umbral - tol and cruce and t_alerta < cruce:
        return "TP", cruce - t_alerta, False
    if mmi >= umbral + tol:
        return "FN", None, t_alerta is not None
    if t_alerta is not None and mmi < umbral - tol:
        return "FP", None, False
    return "TN", None, False


def resumen(clases):
    """Cuentas y tasas de una lista de resultados de clasificar()."""
    k = {"TP": 0, "FP": 0, "FN": 0, "TN": 0, "tarde": 0, "aviso_s": []}
    for c in clases:
        if c is None:
            continue
        clase, aviso, tarde = c
        k[clase] += 1
        k["tarde"] += tarde
        if aviso is not None:
            k["aviso_s"].append(aviso)
    pos = k["TP"] + k["FN"]
    k["TPR"] = k["TP"] / pos if pos else None
    k["FPR"] = k["FP"] / pos if pos else None
    k["CAR"] = k["TP"] / (k["TP"] + k["FP"]) if k["TP"] + k["FP"] else None
    k["aviso_mediana"] = statistics.median(k["aviso_s"]) if k["aviso_s"] else None
    return k


def _f(x, fmt):
    return format(x, fmt) if x is not None else "-"


CABEZA = (f"  {'':38} {'TP':>4} {'FN':>4} {'(tarde)':>7} {'FP':>5} {'TN':>6}"
          f" {'TPR':>5} {'FPR':>6} {'CAR':>5} {'aviso':>6}")


def fila(nombre, k):
    return (f"  {nombre:38} {k['TP']:4} {k['FN']:4} {k['tarde']:7} {k['FP']:5} {k['TN']:6}"
            f" {_f(k['TPR'], '5.2f')} {_f(k['FPR'], '6.2f')} {_f(k['CAR'], '5.2f')}"
            f" {_f(k['aviso_mediana'], '5.0f')}s")


# Tiempo de aviso (s) y MMI observada en que se agrupa el error de predicción
TRAMOS_AVISO = ((60, 1e9), (30, 60), (15, 30), (5, 15), (0, 5), (-1e9, 0))
TRAMOS_MMI = ((1, 2), (2, 3), (3, 4), (4, 11))


def tabla_error(muestras):
    """Mediana de ΔMMI por tramo de tiempo de aviso (filas) y de MMI observada (columnas).

    muestras: (mmi_observada, tiempo_de_aviso_s, delta_mmi), una por predicción.
    """
    lineas = ["  aviso (s)   " + "".join(f"  MMI {a}-{b if b < 11 else '+'}".ljust(16)
                                         for a, b in TRAMOS_MMI)]
    for lo, hi in TRAMOS_AVISO:
        nombre = f">{lo}" if hi > 1e8 else ("<0 (tarde)" if lo < -1e8 else f"{lo}-{hi}")
        celdas = []
        for a, b in TRAMOS_MMI:
            d = [m[2] for m in muestras if a <= m[0] < b and lo <= m[1] < hi]
            celdas.append((f"{statistics.median(d):+.1f} (n={len(d)})" if d else "-").ljust(16))
        lineas.append(f"  {nombre:11} " + "".join(celdas))
    return "\n".join(lineas)
