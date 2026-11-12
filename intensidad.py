"""Intensidad de Mercalli (MMI): la que se predice para un sitio y la que mide una estación.

La usan la alerta (MMI prevista en Medellín, decisión del 23-oct-2026) y la evaluación
(evaluacion/), que la importa desde aquí.

- Predicción: ecuación de intensidad de Allen, Wald y Worden (2012), versión con distancia
  hipocentral, para regiones tectónicamente activas. Coeficientes copiados de OpenQuake
  (openquake/hazardlib/gsim/allen_2012_ipe.py, clase AllenEtAl2012Rhypo).
- Observación: conversión de velocidad (o aceleración) máxima a MMI de Worden et al. (2012),
  con la extensión de ShakeMap para intensidades 1-2. Coeficientes copiados de
  esi-shakelib 1.2.1 (gmice/wgrw12.py), sin los términos de magnitud y distancia.
"""
import json
import math
from pathlib import Path

import numpy as np

import config

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


def mmi_aww12(mag, rhyp_km):
    """MMI media de Allen, Wald y Worden (2012), sin ninguna corrección."""
    c = AWW12
    rm = c["m1"] + c["m2"] * math.exp(mag - 5)
    mmi = c["c0"] + c["c1"] * mag + c["c2"] * math.log(math.sqrt(rhyp_km ** 2 + rm ** 2))
    if rhyp_km > 50:
        mmi += c["c4"] * math.log(rhyp_km / 50)
    return mmi


def _con_magnitud(f, mag, rhyp_km, sigma, sigma_mag):
    """Suma a sigma la incertidumbre de la magnitud, con la pendiente de f frente a M."""
    if not sigma_mag:
        return sigma
    pendiente = (f(mag + 0.05, rhyp_km) - f(mag - 0.05, rhyp_km)) / 0.1
    return math.hypot(sigma, pendiente * sigma_mag)


def mmi_prevista(mag, rhyp_km, sigma_mag=0.0):
    """MMI media prevista y su desviación estándar (Allen, Wald y Worden, 2012), para un sitio
    cualquiera. Para Medellín, mmi_medellin.

    sigma_mag suma la incertidumbre de la magnitud (estimada en vivo) a la de la ecuación,
    con la pendiente de la MMI frente a la magnitud en ese punto.
    """
    c = AWW12
    sigma = c["s1"] + c["s2"] / (1 + (rhyp_km / c["s3"]) ** 2)
    return mmi_aww12(mag, rhyp_km), _con_magnitud(mmi_aww12, mag, rhyp_km, sigma, sigma_mag)


def _correccion():
    path = Path(__file__).parent / "intensidad_medellin.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# Corrección de AWW12 para Medellín, calibrada con la MMI medida en HEL
# (tools/calibrar_intensidad.py -> intensidad_medellin.json): MMI = AWW12 + a + b·ln(R/100),
# con a y b distintos para los sismos someros y los de profundidad intermedia. Sin el archivo,
# mmi_medellin es AWW12 sin corregir.
CORRECCION_MEDELLIN = _correccion()


def _mmi_medellin_media(mag, rhyp_km, prof_km):
    mmi = mmi_aww12(mag, rhyp_km)
    c = CORRECCION_MEDELLIN
    if c:
        zona = c["intermedio" if prof_km >= config.INTENSIDAD_PROF_INTERMEDIA_KM else "somero"]
        mmi += zona["a"] + zona["b"] * math.log(max(rhyp_km, 1.0) / 100)
    return mmi + config.INTENSIDAD_SITIO_MEDELLIN


def mmi_medellin(mag, rhyp_km, prof_km, sigma_mag=0.0):
    """MMI media prevista en Medellín y su desviación: AWW12 con la corrección calibrada en HEL
    (CORRECCION_MEDELLIN, que depende de la profundidad) y el término de sitio de la ciudad
    frente a HEL (config.INTENSIDAD_SITIO_MEDELLIN)."""
    if not CORRECCION_MEDELLIN:
        mmi, sigma = mmi_prevista(mag, rhyp_km, sigma_mag)
        return mmi + config.INTENSIDAD_SITIO_MEDELLIN, sigma

    def f(m, r):
        return _mmi_medellin_media(m, r, prof_km)
    return f(mag, rhyp_km), _con_magnitud(f, mag, rhyp_km, CORRECCION_MEDELLIN["sigma"], sigma_mag)


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


def mmi_sitio(sitio, mag, rhyp_km, prof_km, sigma_mag=0.0):
    """MMI prevista en una estación de la red: la de Medellín (HEL) con la corrección calibrada
    (mmi_medellin, sin el término de sitio de la ciudad, que no aplica a HEL) y las demás con
    AWW12 sin corregir."""
    if sitio == config.LOCAL_STATION:
        mmi, sigma = mmi_medellin(mag, rhyp_km, prof_km, sigma_mag)
        return mmi - config.INTENSIDAD_SITIO_MEDELLIN, sigma
    return mmi_prevista(mag, rhyp_km, sigma_mag)
