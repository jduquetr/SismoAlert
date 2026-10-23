"""Intensidad de Mercalli (MMI): la que se predice para un sitio y la que mide una estación.

Sirve para evaluar las alertas por sitio al estilo de Meier (2017), y más adelante para
predecir la intensidad en Medellín en vivo cuando haya magnitud preliminar.

- Predicción: ecuación de intensidad de Allen, Wald y Worden (2012), versión con distancia
  hipocentral, para regiones tectónicamente activas. Coeficientes copiados de OpenQuake
  (openquake/hazardlib/gsim/allen_2012_ipe.py, clase AllenEtAl2012Rhypo).
- Observación: conversión de aceleración y velocidad máximas a MMI de Worden et al. (2012),
  con la extensión de ShakeMap para intensidades 1-2. Coeficientes copiados de
  esi-shakelib 1.2.1 (gmice/wgrw12.py), sin los términos de magnitud y distancia.
"""
import math

import numpy as np

# Allen, Wald y Worden (2012), distancia hipocentral
AWW12 = dict(c0=2.085, c1=1.428, c2=-1.402, c4=0.078, m1=-0.209, m2=2.042,
             s1=0.82, s2=0.37, s3=22.9)

# Worden et al. (2012): MMI = C1 + C2·log10(Y) hasta T1 y C3 + C4·log10(Y) desde T1, con
# Y en cm/s² (PGA) o cm/s (PGV). Por debajo de T1_BAJO, el tramo de ShakeMap (C1_BAJO...)
WGRW12 = {
    "pga": dict(C1=1.78, C2=1.55, C3=-1.60, C4=3.70, T1=1.57,
                C1_BAJO=1.71, C2_BAJO=2.08, T1_BAJO=0.14),
    "pgv": dict(C1=3.78, C2=1.47, C3=2.89, C4=3.16, T1=0.53,
                C1_BAJO=4.62, C2_BAJO=2.17, T1_BAJO=-1.21),
}


def mmi_prevista(mag, rhyp_km):
    """MMI media prevista y su desviación estándar (Allen, Wald y Worden, 2012)."""
    c = AWW12
    rm = c["m1"] + c["m2"] * math.exp(mag - 5)
    mmi = c["c0"] + c["c1"] * mag + c["c2"] * math.log(math.sqrt(rhyp_km ** 2 + rm ** 2))
    if rhyp_km > 50:
        mmi += c["c4"] * math.log(rhyp_km / 50)
    sigma = c["s1"] + c["s2"] / (1 + (rhyp_km / c["s3"]) ** 2)
    return mmi, sigma


def prob_excedencia(mmi, sigma, umbral):
    """Probabilidad de que la MMI real supere el umbral (distribución normal)."""
    return 0.5 * math.erfc((umbral - mmi) / (sigma * math.sqrt(2)))


def mmi_de_movimiento(y, tipo):
    """MMI de una aceleración (cm/s², tipo "pga") o velocidad (cm/s, "pgv"); acepta arreglos."""
    c = WGRW12[tipo]
    ly = np.log10(np.maximum(np.asarray(y, dtype=float), 1e-9))
    mmi = np.where(ly < c["T1_BAJO"], c["C1_BAJO"] + c["C2_BAJO"] * ly,
                   np.where(ly < c["T1"], c["C1"] + c["C2"] * ly, c["C3"] + c["C4"] * ly))
    return np.clip(mmi, 1.0, 10.0)


def mmi_observada(pga, pgv=None):
    """MMI de una estación como ShakeMap 4 (coremods/model.py, _derive_mmi_from_imts): la de
    PGV si la hay y, si no, la de PGA. Con la de PGA, el Mw7,7 de Panamá del 9-oct (600 km)
    daba MMI 1 en HEL; su energía llega en periodos largos, que la PGV sí recoge."""
    if pgv is not None:
        return mmi_de_movimiento(pgv, "pgv")
    return mmi_de_movimiento(pga, "pga")
