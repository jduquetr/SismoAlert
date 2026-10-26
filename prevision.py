"""Intensidad prevista en Medellín y decisión de alertar, siempre del lado seguro.

Como la JMA (Kodera et al., 2021), se prevé la intensidad de varias maneras y se toma la
que más probabilidad da de superar config.ALERTA_MMI:

- "magnitud": la magnitud preliminar y la ubicación, con la ecuación de intensidad de Allen,
  Wald y Worden (2012). Mientras la estación más cercana no completa su ventana de 30 s se
  usa la magnitud más PREVISION_MARGEN_MAG (arranca baja); después, más su incertidumbre.
- "plum-HEL": la intensidad que ya mide HEL, a 8 km, vale para Medellín (PLUM).
- "plum-EST": la que mide otra estación del sismo, llevada hasta Medellín suponiendo el sismo
  a PLUM_FUENTE_KM de ella (sin ubicarlo). Con la red tan rala, no hay otra estación a menos
  de 30 km de Medellín: es la versión extendida de PLUM.
- "pd-HEL": la PGV que prevé el Pd de los primeros 3 s de la P en HEL (alerta en el sitio).

Una alerta dada no se retira: "alerta" y "alerta_desde" quedan aunque la previsión baje.
"""
import config
import intensidad
import sacudida
from ubicador import _distance_km


def _km_a_medellin(lat, lon):
    return float(_distance_km(lat, lon, *config.MEDELLIN))


def _m_de_intensidad(mmi, r_km):
    """Magnitud que daría esa intensidad a esa distancia hipocentral (bisección)."""
    lo, hi = 0.0, 9.5
    for _ in range(40):
        m = (lo + hi) / 2
        if intensidad.mmi_prevista(m, r_km)[0] < mmi:
            lo = m
        else:
            hi = m
    return (lo + hi) / 2


def candidatos(picks, loc, mag, now):
    """[(fuente, mmi, sigma)] para Medellín. picks: {estación: {"onset", "amps"}}."""
    out = []
    if mag and loc is not None:
        r = float(max(1.0, (_km_a_medellin(loc.lat, loc.lon) ** 2 + loc.depth ** 2) ** 0.5))
        margen = mag.get("incertidumbre") or 0.0
        if not any(now - picks[s]["onset"] >= max(config.MAGNITUD_VENTANAS_S)
                   for s in mag.get("estaciones", {}) if s in picks):
            margen = max(margen, config.PREVISION_MARGEN_MAG)
        mmi, sigma = intensidad.mmi_prevista(mag["valor"] + margen, r, mag.get("incertidumbre") or 0)
        out.append(("magnitud", mmi, sigma))
    for sta, p in picks.items():
        a = p.get("amps") or {}
        if sta not in config.STATIONS:
            continue
        d = _km_a_medellin(*config.STATIONS[sta][3:5])
        if a.get("mmi"):
            if d <= config.PLUM_RADIO_KM:
                out.append((f"plum-{sta}", a["mmi"], config.PLUM_SIGMA))
            else:
                m = _m_de_intensidad(a["mmi"], config.PLUM_FUENTE_KM)
                mmi, sigma = intensidad.mmi_prevista(m, max(d, config.PLUM_FUENTE_KM))
                out.append((f"plum-{sta}", mmi, sigma))
        pd = a.get("pd") or {}
        if (d <= config.PLUM_RADIO_KM and pd.get("pd_cm", 0) > 0
                and (pd.get("snr") or 0) >= config.PD_SNR_MIN):
            mmi = float(sacudida.mmi(sacudida.pgv_de_pd(pd["pd_cm"])))
            out.append((f"pd-{sta}", mmi, config.PD_SIGMA))
    return out


def medellin(picks, loc, mag, now, previo=None):
    """El campo det["medellin"]: la previsión de más probabilidad y si se alerta.

    previo: el valor anterior del mismo sismo (la alerta no se retira).
    """
    previo = previo or {}
    umbral = config.ALERTA_MMI
    mejor = None
    for fuente, mmi, sigma in candidatos(picks, loc, mag, now):
        p = intensidad.prob_excedencia(mmi, sigma, umbral)
        if mejor is None or (p, mmi) > (mejor[0], mejor[2]):
            mejor = (p, fuente, mmi, sigma)
    out = {"umbral": umbral, "alerta": bool(previo.get("alerta")),
           "alerta_desde": previo.get("alerta_desde")}
    if mejor:
        p, fuente, mmi, sigma = mejor
        out.update(mmi=round(min(max(float(mmi), 1.0), 10.0), 1), sigma=round(float(sigma), 2),
                   prob=round(float(p), 2), fuente=fuente)
        if p >= config.ALERTA_PROB and not out["alerta"]:
            out.update(alerta=True, alerta_desde=str(now), alerta_fuente=fuente)
    if previo.get("alerta_fuente"):
        out["alerta_fuente"] = previo["alerta_fuente"]
    local = picks.get(config.LOCAL_STATION)
    a = (local or {}).get("amps") or {}
    if a.get("mmi") is not None:
        out["observada"] = {"mmi": a["mmi"], "cruces": dict(a.get("cruces", {}))}
    pd = a.get("pd") or {}
    if pd.get("tauc_s"):
        out["pd"] = {"pd_cm": float(f"{pd['pd_cm']:.3g}"), "tauc_s": pd["tauc_s"],
                     "m_tauc": round(sacudida.m_de_tauc(pd["tauc_s"]), 1), "snr": pd.get("snr")}
    return out


def cambio(a, b):
    """¿Cambió la previsión lo bastante para avisar (y anotarlo en el registro)?"""
    a, b = a or {}, b or {}
    if a.get("alerta") != b.get("alerta") or a.get("fuente") != b.get("fuente"):
        return True
    if abs((a.get("mmi") or 0) - (b.get("mmi") or 0)) >= 0.5:
        return True
    ca = (a.get("observada") or {}).get("cruces", {})
    cb = (b.get("observada") or {}).get("cruces", {})
    return set(ca) != set(cb)


def texto(prev):
    if not prev or prev.get("mmi") is None:
        return ""
    f = prev["fuente"]
    fuente = ("por magnitud y ubicación" if f == "magnitud"
              else f"por los primeros segundos en {f[3:]}" if f.startswith("pd-")
              else f"por lo que ya mide {f[5:]}")
    if prev.get("alerta"):
        return f"ALERTA PARA MEDELLÍN: intensidad prevista {prev['mmi']:.1f} ({fuente})"
    if prev["mmi"] < config.ALERTA_MMI:
        return (f"No se espera que se sienta en Medellín (intensidad prevista {prev['mmi']:.1f}, "
                f"{fuente})")
    return f"Medellín: intensidad prevista {prev['mmi']:.1f} ({fuente})"
