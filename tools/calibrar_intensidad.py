"""Calibra la ecuación de intensidad para Medellín con la intensidad medida en HEL.

La ecuación de Allen, Wald y Worden (2012) es para sismos de corteza. En Medellín se pasa con
los sismos someros cercanos y se queda corta con los de profundidad intermedia (el nido de
Bucaramanga, la placa de Nazca bajo el Eje Cafetero), que son los que más se sienten. Aquí se
mide la MMI en HEL (suma vectorial de las horizontales, como evaluacion/observado.py) de los
sismos del USGS desde que existe HEL y se ajusta una corrección

    MMI = AWW12(M, Rhip) + a_zona + b_zona · ln(Rhip / 100)

con zona = "somero" (< INTENSIDAD_PROF_INTERMEDIA_KM) o "intermedio". La mayoría de los sismos
no se sienten en HEL: su MMI medida es la del ruido, y solo dice que la verdadera fue menor.
Por eso el ajuste es por máxima verosimilitud con censura (Tobit): un sismo cuya MMI no supera
el ruido aporta la probabilidad de quedar por debajo, no un valor.

    python tools/calibrar_intensidad.py catalogo --salida cal/cat.json
    python tools/calibrar_intensidad.py medir --catalogo cal/cat.json --obs cal/obs_hel.json
    python tools/calibrar_intensidad.py ajustar --catalogo cal/cat.json --obs cal/obs_hel.json

`ajustar` imprime los coeficientes para intensidad.CORRECCION_MEDELLIN y la comparación con
la ecuación sin corregir. Los sismos se reparten en ajuste y validación (los años impares
validan) para no juzgar con los mismos datos con que se ajusta.
"""
import argparse
import json
import math
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from obspy import UTCDateTime  # noqa: E402
from scipy.optimize import minimize  # noqa: E402
from scipy.special import log_ndtr  # noqa: E402

import config  # noqa: E402
import intensidad  # noqa: E402
import sources  # noqa: E402
from evaluacion import catalogo, observado  # noqa: E402
from evaluacion.fuentes import ClienteMixto  # noqa: E402

DESDE = UTCDateTime("2011-06-18")  # inicio de CM.HEL
MAG_MIN, RADIO_KM = 3.5, 1000
# Solo se miden los sismos que la ecuación, con 2 grados de holgura, deja en MMI ≥ 1,5: el resto
# no tiene cómo sentirse en HEL y solo alarga la descarga
HOLGURA = 2.0
# Una MMI medida cuenta como valor (no censurada) si supera el ruido en este margen y llega a 1,5
MARGEN_RUIDO = 0.3
MMI_MIN_VALOR = 1.5
HEL = config.STATIONS[config.LOCAL_STATION]


def _rhyp_hel(ev):
    return catalogo.rhyp(ev, *HEL[3:5])


def _json_ev(e):
    return {k: (str(v) if k == "time" else v) for k, v in e.items()}


def _de_json(e):
    return dict(e, time=UTCDateTime(e["time"]))


def bajar(args):
    evs = catalogo.usgs_historico(DESDE, UTCDateTime(), MAG_MIN, RADIO_KM)
    evs = [e for e in evs if e.get("mag") is not None and e.get("lat") is not None]
    keep = [e for e in evs
            if intensidad.mmi_aww12(e["mag"], _rhyp_hel(e)) + HOLGURA >= MMI_MIN_VALOR]
    print(f"{len(evs)} sismos, {len(keep)} con alguna posibilidad de sentirse en HEL",
          file=sys.stderr)
    Path(args.salida).parent.mkdir(parents=True, exist_ok=True)
    json.dump([_json_ev(e) for e in keep], open(args.salida, "w", encoding="utf-8"))


def _medir_hel(ev, client, inv):
    net, loc, cha, lat, lon = HEL
    tp = catalogo.tiempo_p(ev, lat, lon)
    bulk = [(net, config.LOCAL_STATION, loc or "--", cha[:2] + "?", ev["time"] - 90,
             ev["time"] + min(1.8 * tp + 150, 900))]
    st = client.get_waveforms_bulk(bulk)
    st.merge(method=1, fill_value=0)
    return observado._medir_sitio(st.select(channel=cha[:2] + "?"), inv, ev, lat, lon)


def medir(args):
    evs = [_de_json(e) for e in json.load(open(args.catalogo, encoding="utf-8"))]
    cache = json.load(open(args.obs, encoding="utf-8")) if os.path.exists(args.obs) else {}
    # Los errores de red se reintentan; "faltan componentes" es que el archivo no tiene datos
    faltan = [e for e in evs if catalogo.clave(e) not in cache
              or "faltan componentes" not in cache[catalogo.clave(e)].get("error", "faltan componentes")]
    print(f"{len(faltan)} por medir de {len(evs)}", file=sys.stderr)
    if not faltan:
        return
    net, loc, cha, *_ = HEL
    inv = ClienteMixto().get_stations(network=net, station=config.LOCAL_STATION,
                                      location=loc or "--", channel=cha[:2] + "?",
                                      level="response")
    local = threading.local()

    def uno(e):
        if not hasattr(local, "client"):
            local.client = ClienteMixto()
        try:
            return catalogo.clave(e), _medir_hel(e, local.client, inv)
        except Exception as err:
            return catalogo.clave(e), {"error": f"{type(err).__name__}: {err}"[:200]}

    with ThreadPoolExecutor(args.hilos) as pool:
        for i, (k, v) in enumerate(pool.map(uno, faltan), 1):
            cache[k] = v
            if i % 50 == 0 or i == len(faltan):
                json.dump(cache, open(args.obs, "w", encoding="utf-8"))
                print(f"  {i}/{len(faltan)}", file=sys.stderr)


def datos(cat_path, obs_path):
    """Filas (M, Rhip, prof, mmi, censurada, año) de los sismos medidos sin error ni saturación."""
    evs = [_de_json(e) for e in json.load(open(cat_path, encoding="utf-8"))]
    obs = json.load(open(obs_path, encoding="utf-8"))
    filas = []
    for e in evs:
        o = obs.get(catalogo.clave(e))
        if not o or "error" in o or o.get("saturada"):
            continue
        valor = o["mmi"] >= MMI_MIN_VALOR and o["mmi"] >= o["ruido_mmi"] + MARGEN_RUIDO
        # Censurada: la verdadera quedó por debajo del ruido (o de 1,5 si el ruido era menor)
        tope = o["mmi"] if valor else max(o["ruido_mmi"] + MARGEN_RUIDO, MMI_MIN_VALOR)
        filas.append((e["mag"], _rhyp_hel(e), e.get("depth") or 10, tope, not valor,
                      e["time"].year, catalogo.clave(e)))
    return filas


def _zona(prof):
    return np.where(np.asarray(prof) >= config.INTENSIDAD_PROF_INTERMEDIA_KM, 1, 0)


def _pred(theta, m, r, z):
    a = np.array([theta[0], theta[2]])[z]
    b = np.array([theta[1], theta[3]])[z]
    base = np.array([intensidad.mmi_aww12(mi, ri) for mi, ri in zip(m, r)])
    return base + a + b * np.log(r / 100)


def _nll(theta, m, r, z, y, cens):
    mu = _pred(theta, m, r, z)
    s = math.exp(theta[4])
    zz = (y - mu) / s
    ll = np.where(cens, log_ndtr(zz), -0.5 * zz ** 2 - math.log(s) - 0.5 * math.log(2 * math.pi))
    # Regularización suave: sin datos de una zona, la corrección se queda cerca de 0
    return -ll.sum() + 0.5 * np.sum(np.asarray(theta[:4]) ** 2) / 1.0 ** 2


def ajustar_filas(filas):
    m, r, p, y, cens = (np.array([f[i] for f in filas], dtype=float) for i in range(5))
    cens = cens.astype(bool)
    z = _zona(p)
    res = minimize(_nll, x0=[0, 0, 0, 0, math.log(0.8)], args=(m, r, z, y, cens),
                   method="Nelder-Mead", options=dict(maxiter=20000, xatol=1e-4, fatol=1e-6))
    return res.x


def _resumen(nombre, filas, theta):
    """Sesgo y aciertos (sentido = MMI ≥ 2, con P ≥ 0,5) en los sismos no censurados y totales."""
    m, r, p, y, cens = (np.array([f[i] for f in filas], dtype=float) for i in range(5))
    cens = cens.astype(bool)
    z = _zona(p)
    mu = _pred(theta, m, r, z) if theta is not None else np.array(
        [intensidad.mmi_aww12(mi, ri) for mi, ri in zip(m, r)])
    sentido = ~cens & (y >= 2.0)
    avisa = mu >= 2.0
    out = [f"{nombre}:"]
    for zn, etiqueta in ((0, "somero"), (1, "intermedio")):
        k = ~cens & (z == zn)
        if k.any():
            out.append(f"  {etiqueta}: {k.sum()} medidos, sesgo {np.mean(y[k] - mu[k]):+.2f}, "
                       f"desv. {np.std(y[k] - mu[k]):.2f}")
    tp = int((sentido & avisa).sum())
    out.append(f"  sentidos en HEL {int(sentido.sum())}: avisa {tp}, pierde "
               f"{int((sentido & ~avisa).sum())}; avisa sin sentirse {int((~sentido & avisa).sum())}")
    return "\n".join(out)


def ajustar(args):
    filas = datos(args.catalogo, args.obs)
    print(f"{len(filas)} sismos medidos, {sum(1 for f in filas if not f[4])} sobre el ruido")
    ajuste = [f for f in filas if f[5] % 2 == 0]
    valida = [f for f in filas if f[5] % 2 == 1]
    th = ajustar_filas(ajuste)
    print("\nAjuste con los años pares; validación con los impares")
    print(_resumen("Validación, AWW12 sin corregir", valida, None))
    print(_resumen("Validación, AWW12 corregida", valida, th))
    final = ajustar_filas(filas)
    print("\nCon todos los años (lo que va en intensidad.py):")
    print(_resumen("Todos, AWW12 sin corregir", filas, None))
    print(_resumen("Todos, AWW12 corregida", filas, final))
    coef = {"somero": {"a": round(final[0], 2), "b": round(final[1], 2)},
            "intermedio": {"a": round(final[2], 2), "b": round(final[3], 2)},
            "sigma": round(math.exp(final[4]), 2)}
    print("\nCORRECCION_MEDELLIN =", json.dumps(coef))
    if args.salida:
        json.dump(dict(coef, sismos=len(filas), sobre_ruido=sum(1 for f in filas if not f[4]),
                       fuente=f"USGS M>={MAG_MIN} a <{RADIO_KM} km, MMI medida en HEL, "
                              f"{DESDE.date} a {UTCDateTime().date}"),
                  open(args.salida, "w", encoding="utf-8"), indent=1)


def umbral(args):
    """Aciertos y falsas en Medellín según el umbral de probabilidad, antes y después.

    Con la magnitud y la ubicación del catálogo más un error de magnitud simulado (normal,
    sigma = --sigma-mag, como la incertidumbre que da magnitud.estimar a los 30 s), para cada
    sismo medido en HEL. "Antes" es la regla de hasta nov-2026 (AWW12 sin corregir con la
    incertidumbre sumada a la magnitud y también en la sigma, p ≥ 0,5); "ahora", mmi_medellin
    con la incertidumbre solo en la sigma. Sentido = MMI ≥ 2 medida en HEL; con tolerancia
    (Meier, 2017) una alerta es falsa solo si HEL quedó por debajo de 1,5.
    """
    filas = datos(args.catalogo, args.obs)
    rng = np.random.default_rng(1)
    sm = args.sigma_mag
    y = np.array([f[3] for f in filas])
    cens = np.array([f[4] for f in filas])
    sentido = ~cens & (y >= 2.0)
    fuerte = ~cens & (y >= 2.5)  # con tolerancia, solo es perdida si superó 2,5
    bajo = cens | (y < 1.5)
    errs = rng.normal(0, sm, (args.repeticiones, len(filas)))

    def tabla(nombre, prob, umbrales):
        ps = [np.array([prob(f[0] + de, f[1], f[2]) for f, de in zip(filas, e)]) for e in errs]
        print(f"\n{nombre}  ({int(sentido.sum())} sentidos en HEL, {int(fuerte.sum())} con "
              f"MMI >= 2,5, {len(filas)} sismos)")
        print("  p*    aciertos  perdidos  perdidos(tol)  falsas  falsas(tol)  CAR")
        for u in umbrales:
            tp = np.mean([np.sum(sentido & (p >= u)) for p in ps])
            fn = sentido.sum() - tp
            fp = np.mean([np.sum(~sentido & (p >= u)) for p in ps])
            fpt = np.mean([np.sum(bajo & (p >= u)) for p in ps])
            fnt = np.mean([np.sum(fuerte & (p < u)) for p in ps])
            print(f"  {u:.2f}  {tp:8.1f}  {fn:8.1f}  {fnt:13.1f}  {fp:6.1f}  {fpt:11.1f}  "
                  f"{tp / max(tp + fp, 1e-9):.2f}")

    def antes(m, r, prof):
        mmi, s = intensidad.mmi_prevista(m + sm, r, sm)
        return intensidad.prob_excedencia(mmi, s, 2.0)

    def ahora(m, r, prof):
        mmi, s = intensidad.mmi_medellin(m, r, prof, sm)
        return intensidad.prob_excedencia(mmi, s, 2.0)

    tabla("Antes (AWW12, incertidumbre contada dos veces)", antes, [0.5])
    tabla("Ahora (corregida, incertidumbre solo en la sigma)", ahora,
          [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("catalogo")
    a.add_argument("--salida", required=True)
    a = sub.add_parser("medir")
    a.add_argument("--catalogo", required=True)
    a.add_argument("--obs", required=True)
    a.add_argument("--hilos", type=int, default=6)
    a = sub.add_parser("ajustar")
    a.add_argument("--catalogo", required=True)
    a.add_argument("--obs", required=True)
    a.add_argument("--salida")
    a = sub.add_parser("umbral")
    a.add_argument("--catalogo", required=True)
    a.add_argument("--obs", required=True)
    a.add_argument("--sigma-mag", type=float, default=0.35)
    a.add_argument("--repeticiones", type=int, default=30)
    args = ap.parse_args()
    {"catalogo": bajar, "medir": medir, "ajustar": ajustar, "umbral": umbral}[args.cmd](args)


if __name__ == "__main__":
    main()
