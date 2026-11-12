"""Umbral de la alerta por magnitud con el lote histórico repasado (evaluacion/lote_historico.py).

Sobre las decisiones del repaso (asociador bayesiano), vuelve a calcular la probabilidad de la
previsión por magnitud con la regla anterior (AWW12, incertidumbre contada dos veces, p 0,5) y
con la actual para varios umbrales, con y sin el sesgo temprano PREVISION_MARGEN_MAG. Las
alertas de PLUM y Pd se toman como quedaron en el repaso. Un sismo es sentido si HEL midió
MMI >= ALERTA_MMI; el aviso es el tiempo entre la alerta y el cruce de MMI 2 en HEL.

Si el repaso registró la probabilidad de la magnitud (medellin.prob_magnitud, desde que la
previsión mezcla la nube de epicentros del ubicador), se barre también esa ("registrada"),
que no se puede recalcular desde el registro.

  python tools/umbral_repaso.py lote/decisiones.jsonl lote/obs.json
"""
import collections
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from obspy import UTCDateTime as T  # noqa: E402

import config  # noqa: E402
import intensidad  # noqa: E402
import prevision  # noqa: E402

U = config.ALERTA_MMI


def p_magnitud(d, regla, sesgo):
    if regla == "registrada":
        return (d.get("medellin") or {}).get("prob_magnitud")
    loc, mag = d.get("ubicacion"), d.get("magnitud")
    if not loc or not mag:
        return None
    r = max(1.0, (prevision._km_a_medellin(loc["lat"], loc["lon"]) ** 2 + loc["depth"] ** 2) ** 0.5)
    now, unc = T(d["emitida"]), mag.get("incertidumbre") or 0
    temprano = not any(now - T(d["estaciones"][s]["onset"]) >= max(config.MAGNITUD_VENTANAS_S)
                       for s in mag.get("estaciones", {}) if s in d["estaciones"])
    if regla == "anterior":
        m = mag["valor"] + (max(unc, 0.5) if temprano else unc)
        return intensidad.prob_excedencia(*intensidad.mmi_prevista(m, r, unc), U)
    m = mag["valor"] + (sesgo if temprano else 0)
    return intensidad.prob_excedencia(*intensidad.mmi_medellin(m, r, loc["depth"], unc), U)


def evaluar(ev, obs, regla, pstar, sesgo):
    tp = fn = fp = 0
    avisos, perdidos = [], []
    for k, ds in ev.items():
        o = (obs.get(k) or {}).get(config.LOCAL_STATION) or {}
        if "mmi" not in o:
            continue
        t_al = None
        for d in ds:
            m = d.get("medellin") or {}
            if m.get("alerta") and not str(m.get("alerta_fuente", "")).startswith("magnitud"):
                t_al = T(d["emitida"])
                break
            p = p_magnitud(d, regla, sesgo)
            if p is not None and p >= pstar:
                t_al = T(d["emitida"])
                break
        if o["mmi"] >= U:
            if t_al is None:
                fn += 1
                perdidos.append(round(o["mmi"], 1))
            else:
                tp += 1
                if o["cruces"].get("2.0"):
                    avisos.append(T(o["cruces"]["2.0"]) - t_al)
        elif t_al is not None:
            fp += 1
    return tp, fn, fp, (statistics.median(avisos) if avisos else float("nan")), perdidos


def main():
    ev = collections.defaultdict(list)
    for line in open(sys.argv[1], encoding="utf-8"):
        d = json.loads(line)
        if d.get("asociador") == "bayesiano":
            ev[d["sismo_repasado"]].append(d)
    obs = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    print("regla                       aciertos perdidos falsas  aviso mediano (s)  perdidos (MMI)")
    filas = [("anterior, p 0,5", "anterior", 0.5, 0.5)]
    filas += [(f"actual, p {p:.2f}, sesgo {s}", "actual", p, s)
              for p in (0.15, 0.2, 0.3, 0.4, 0.5) for s in (0.5, 0.0)]
    if any("prob_magnitud" in (d.get("medellin") or {}) for ds in ev.values() for d in ds):
        filas += [(f"registrada, p {p:.2f}", "registrada", p, 0)
                  for p in (0.15, 0.2, 0.3, 0.4, 0.5)]
    for nombre, regla, pstar, sesgo in filas:
        tp, fn, fp, med, per = evaluar(ev, obs, regla, pstar, sesgo)
        print(f"{nombre:28} {tp:6} {fn:8} {fp:7}  {med:12.0f}       {per}")


if __name__ == "__main__":
    main()
