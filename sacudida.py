"""Cuánto está sacudiendo en una estación, medido en vivo, sin ubicar ni dimensionar el sismo.

Dos medidas, ambas solo hacia atrás en el tiempo (filtros causales), como en vivo:

- PGV: velocidad máxima del suelo, suma vectorial de las dos horizontales (como ShakeMap y
  la evaluación, Meier 2017). De ella sale la intensidad observada (intensidad.py, Worden et
  al. 2012). Es lo que usa PLUM (Kodera et al., 2021): la intensidad que ya se mide en una
  estación se toma como la prevista en los sitios cercanos. Si la estación solo manda la
  vertical, se usa la vertical por INTENSIDAD_FACTOR_Z.
- Pd y τc: desplazamiento máximo y periodo característico de los primeros 3 s de la onda P
  en la vertical (Kanamori, 2005; Wu y Kanamori, 2005 y 2008). Con Pd se prevé la PGV que va
  a tener la misma estación cuando llegue la S, y con τc una magnitud, las dos sin saber dónde
  está el sismo. Es la alerta en el propio sitio: para Medellín, con HEL.

Los coeficientes de Pd y τc son los publicados para California del Sur; falta calibrarlos
con HEL.
"""
import math

import numpy as np

import config
import intensidad

# Wu y Kanamori: log10 PGV (cm/s) = A·log10 Pd (cm) + B; M = C·log10 τc + D
PD_A, PD_B = 0.920, 1.642
TAUC_C, TAUC_D = 3.373, 5.787
PD_HIGHPASS_HZ = 0.075
VEL_HIGHPASS_HZ = 0.1


def _velocidad(tr, sens):
    """Velocidad en cm/s, filtro pasaaltos causal. tr: traza cruda (cuentas)."""
    v = tr.copy()
    v.data = v.data.astype(float)
    v.detrend("demean")
    v.taper(0.02, side="left")
    v.filter("highpass", freq=VEL_HIGHPASS_HZ, corners=2, zerophase=False)
    return v.data / sens * 100


def serie(trazas, sens, desde, factor=1.0):
    """PGV (cm/s) muestra a muestra desde la hora `desde`: (hora de la primera, muestreo,
    valores). Suma vectorial si hay dos trazas; si no, |v|·factor. Se ignoran los primeros
    20 s del búfer, donde todavía se nota el arranque del filtro. None si no hay muestras.
    """
    trazas = [t for t in trazas if t.stats.npts]
    if not trazas:
        return None
    df = trazas[0].stats.sampling_rate
    ini = max(max(t.stats.starttime for t in trazas) + 20, desde)
    fin = min(t.stats.endtime for t in trazas)
    if fin <= ini:
        return None
    comp = []
    for t in trazas:
        v = _velocidad(t, sens)
        i0 = int(round((ini - t.stats.starttime) * df))
        i1 = int(round((fin - t.stats.starttime) * df)) + 1
        comp.append(v[i0:i1])
    n = min(len(c) for c in comp)
    if n == 0:
        return None
    if len(comp) >= 2:
        return ini, df, np.hypot(comp[0][:n], comp[1][:n])
    return ini, df, np.abs(comp[0][:n]) * factor


def mmi(pgv_cms):
    """Intensidad de una PGV (cm/s); acepta arreglos."""
    return intensidad.mmi_observada(None, pgv_cms)


def pd_tauc(tr, onset, sens, ventana=3.0):
    """Pd (cm), τc (s) y ruido (cm) de los primeros `ventana` s desde el disparo, o None.

    La traza debe llegar al menos hasta onset + ventana y empezar 20 s antes del disparo.
    """
    df = tr.stats.sampling_rate
    if tr.stats.endtime < onset + ventana or tr.stats.starttime > onset - 20:
        return None
    v = tr.slice(onset - 60, onset + ventana).copy()
    v.data = v.data.astype(float)
    i0 = int(round((onset - v.stats.starttime) * df))
    v.data -= v.data[:i0].mean()  # el promedio de antes del disparo, no el de la señal
    v.data /= sens
    v.taper(0.02, side="left")
    v.filter("highpass", freq=PD_HIGHPASS_HZ, corners=2, zerophase=False)
    vel = v.data.copy()
    u = np.cumsum(vel) / df
    v.data = u
    v.filter("highpass", freq=PD_HIGHPASS_HZ, corners=2, zerophase=False)
    u = v.data * 100  # cm
    i1 = i0 + int(ventana * df)
    seg_u = u[i0:i1]
    ruido = float(np.abs(u[max(0, i0 - int(10 * df)):max(1, i0 - int(df))]).max())
    pd = float(np.abs(seg_u).max())
    du = np.diff(seg_u) * df
    tauc = 2 * math.pi * math.sqrt(np.sum(seg_u ** 2) / max(np.sum(du ** 2), 1e-30))
    return {"pd_cm": pd, "tauc_s": round(tauc, 2), "ruido_cm": ruido,
            "snr": round(pd / ruido, 1) if ruido > 0 else None}


def pgv_de_pd(pd_cm):
    """PGV (cm/s) prevista en la misma estación a partir de Pd."""
    return 10 ** (PD_A * math.log10(pd_cm) + PD_B)


def m_de_tauc(tauc_s):
    return TAUC_C * math.log10(max(tauc_s, 1e-3)) + TAUC_D
