"""Evalúa las alertas para Medellín como propone Meier (2017): por sitio, con la intensidad
que de verdad se registró y el momento en que se superó.

Meier, M.-A. (2017). How "good" are real-time ground motion predictions from Earthquake
Early Warning systems? J. Geophys. Res. Solid Earth 122, 5561-5577. doi:10.1002/2017JB014025

El sitio es Medellín y la "verdad" es HEL (Santa Elena, a 8 km): para cada sismo de
catálogo se baja su registro de EarthScope, se pasa a aceleración y velocidad, y se calcula
la intensidad (MMI, Worden et al., 2012) y el instante en que cruza cada umbral. Luego los
disparos del registro se vuelven a pasar por los dos asociadores, anotando a qué hora llega
cada nivel de alerta, y cada sismo se clasifica para cada umbral de intensidad:

- acierto (TP): se avisó antes de que HEL superara el umbral; el tiempo de aviso es la
  diferencia;
- tarde: se avisó, pero después de superarlo;
- perdido (FN): HEL lo superó y no hubo aviso;
- falsa (FP): se avisó y HEL no llegó al umbral (incluye avisos sin sismo en el catálogo);
- correcto sin aviso (TN).

Dos formas de decidir el aviso:

- Opción A, el sistema como está: hay aviso si una detección del sismo llega al nivel de la
  política ("alta o media", o cualquier nivel). No hay magnitud, así que el aviso no dice
  cuánto va a temblar.
- Opción B, cota ideal: en el momento de la primera detección se supone conocido el sismo
  del catálogo (magnitud y foco), se predice la MMI en Medellín (Allen, Wald y Worden, 2012)
  y se avisa si P(MMI > umbral) > p*. Mide cuánto se pierde solo por la demora en detectar.
  Además, "red ideal": la detección llega con la P a la estación más cercana que vota.

El aviso sale LATENCIA_S después del disparo que lo provoca (SeedLink y procesamiento) y,
como en el artículo, no se puede cancelar.

Uso: python tools/evaluar_alertas.py REGISTRO.json.gz --catalogos cat.pickle
        [--obs obs.json] [--repasos repasos.pickle] [--latencia 15] [--csv salida.csv]
"""
import argparse
import csv
import json
import math
import os
import pickle
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np  # noqa: E402
from obspy import UTCDateTime  # noqa: E402

import config  # noqa: E402
import intensidad  # noqa: E402
import sources  # noqa: E402
from asociador import BayesAssociator  # noqa: E402
from detector import Associator, simultaneous_artifact  # noqa: E402
from evaluar_asociador import TP as TIEMPO_P, load_picks, strict_match  # noqa: E402
from ubicador import Malla  # noqa: E402

UMBRALES = (2.0, 3.0, 4.0)
P_ESTRELLA = (0.1, 0.3, 0.5, 0.7)
POLITICAS = {"alta o media": ("alta", "media"), "cualquier nivel": ("alta", "media", "baja")}
SITIO = config.STATIONS[config.LOCAL_STATION][3:5]
# Retardo de un disparo STA/LTA frente a la P teórica (medido: ~3 s), para la red ideal
RETARDO_DISPARO_S = 3.0
# Sismos cuya intensidad en HEL se mide: los que alguna detección explica y los que la
# ecuación de intensidad no da por imperceptibles en Medellín
MMI_PREVISTA_MIN = 0.0


def rhyp(ev, lat, lon):
    d = sources.distance_km(lat, lon, ev["lat"], ev["lon"])
    return math.hypot(d, ev.get("depth") or 10)


def eventos(cats, start, end):
    """Sismos únicos del periodo; si dos catálogos traen el mismo, se queda el del SGC."""
    unicos = []
    for name in ("SGC", "USGS", "EMSC"):
        for e in sorted(cats.get(name, []), key=lambda e: e["time"]):
            if not start <= e["time"] <= end or e.get("mag") is None:
                continue
            if not any(abs(e["time"] - u["time"]) < 20
                       and sources.distance_km(e["lat"], e["lon"], u["lat"], u["lon"]) < 100
                       for u in unicos):
                unicos.append(e)
    return sorted(unicos, key=lambda e: e["time"])


def canonico(ev, unicos):
    for u in unicos:
        if abs(ev["time"] - u["time"]) < 20 and \
                sources.distance_km(ev["lat"], ev["lon"], u["lat"], u["lon"]) < 100:
            return u
    return None


def clave(ev):
    return f"{ev['source']}:{ev['id']}"


# ---------------------------------------------------------------- intensidad observada


def observar(ev, client, inv):
    """Intensidad en HEL para un sismo: PGA, PGV, MMI, ruido previo y hora de cada cruce."""
    net, loc = config.STATIONS[config.LOCAL_STATION][:2]
    lat, lon = SITIO
    d = sources.distance_km(lat, lon, ev["lat"], ev["lon"])
    tp = float(TIEMPO_P(d, ev.get("depth") or 10))
    t0 = ev["time"]
    st = client.get_waveforms(net, config.LOCAL_STATION, loc, "HH?", t0 - 60,
                              t0 + 1.8 * tp + 150)
    st.merge(method=1, fill_value=0)
    horiz = [tr for tr in st if tr.stats.channel[-1] in "NE12"]
    if len(horiz) < 2:
        raise ValueError("faltan componentes horizontales")
    saturada = any(np.abs(tr.data).max() > 0.9 * 2 ** 23 for tr in horiz)
    curvas = {}
    for salida in ("ACC", "VEL"):
        trs = [tr.copy() for tr in horiz]
        for tr in trs:
            tr.detrend("demean")
            tr.taper(0.05)
            tr.remove_response(inventory=inv, output=salida, pre_filt=(0.05, 0.1, 35, 45),
                               water_level=60)
        n = min(len(tr.data) for tr in trs)
        # La mayor de las dos horizontales, en cm/s² o cm/s
        curvas[salida] = np.max([np.abs(tr.data[:n]) for tr in trs], axis=0) * 100
    n = min(len(c) for c in curvas.values())
    tiempos = trs[0].times(reftime=t0)[:n]
    llega = tiempos >= tp - 5
    # Ruido: lo que había antes de la P (sin los bordes del filtro)
    antes = (tiempos > -50) & ~llega
    ruido = float(intensidad.mmi_observada(curvas["ACC"][antes].max(), curvas["VEL"][antes].max()))
    pga = np.maximum.accumulate(np.where(llega, curvas["ACC"][:n], 0))
    pgv = np.maximum.accumulate(np.where(llega, curvas["VEL"][:n], 0))
    mmi = intensidad.mmi_observada(pga, pgv)
    cruces = {}
    for u in UMBRALES:
        i = np.argmax(mmi >= u)
        cruces[str(u)] = (str(t0 + float(tiempos[i]))
                          if mmi[i] >= u and ruido < u else None)
    return {"mmi": round(float(mmi[-1]), 2), "pga_cms2": round(float(pga[-1]), 4),
            "pgv_cms": round(float(pgv[-1]), 5), "ruido_mmi": round(ruido, 2),
            "saturada": saturada, "cruces": cruces}


def medir(evs, path):
    """Mide (o lee de la caché) la intensidad en HEL de cada sismo."""
    from obspy.clients.fdsn import Client
    cache = json.load(open(path, encoding="utf-8")) if path and os.path.exists(path) else {}
    faltan = [e for e in evs if clave(e) not in cache]
    if faltan:
        client = Client("EARTHSCOPE")
        net, loc = config.STATIONS[config.LOCAL_STATION][:2]
        inv = client.get_stations(network=net, station=config.LOCAL_STATION, location=loc,
                                  channel="HH?", level="response")
        for i, e in enumerate(faltan, 1):
            try:
                cache[clave(e)] = observar(e, client, inv)
            except Exception as err:
                cache[clave(e)] = {"error": f"{type(err).__name__}: {err}"[:200]}
            if i % 20 == 0 or i == len(faltan):
                print(f"  intensidad en HEL: {i}/{len(faltan)}", file=sys.stderr)
                if path:
                    json.dump(cache, open(path, "w", encoding="utf-8"), indent=0)
    return cache


# ---------------------------------------------------------------- repaso de los disparos


def repasar(assoc_cls, picks, **kw):
    """Pasa los disparos por un asociador y anota a qué hora llega cada nivel."""
    dets = {}
    clock = {"now": None}

    def keep(det):
        e = dets.setdefault(det["id"], {"niveles": []})
        e["det"] = det
        e["niveles"].append((clock["now"], det["level"]))

    if assoc_cls is BayesAssociator:
        kw["clock"] = lambda: clock["now"]
    a = assoc_cls(on_detection=keep, on_update=keep, **kw)
    for t, s, r in picks:
        clock["now"] = t
        a.trigger(s, t, r)
    return [{"det": json.loads(json.dumps(e["det"], default=str)), "niveles": e["niveles"]}
            for e in dets.values()]


def avisos(repaso, todos, unicos, latencia):
    """Por sismo: hora del primer aviso de cada nivel. Y la lista de avisos sin sismo."""
    por_sismo, sin_sismo = {}, []
    for r in repaso:
        det = r["det"]
        if simultaneous_artifact(det):
            continue
        ev, _, _ = strict_match(det, todos)
        ev = canonico(ev, unicos) if ev else None
        primero = {}
        for t, lv in r["niveles"]:
            primero.setdefault(lv, t + latencia)
        if ev is None:
            sin_sismo.append(primero)
            continue
        dest = por_sismo.setdefault(clave(ev), {})
        for lv, t in primero.items():
            if lv not in dest or t < dest[lv]:
                dest[lv] = t
    return por_sismo, sin_sismo


def hora_aviso(niveles, politica):
    ts = [t for lv, t in niveles.items() if lv in politica]
    return min(ts) if ts else None


def red_ideal(ev, latencia):
    """Primera P en una estación que vota, más el retardo del disparo y la latencia."""
    tp = min(float(TIEMPO_P(sources.distance_km(ev["lat"], ev["lon"], *v[3:5]),
                            ev.get("depth") or 10)) for v in config.STATIONS.values())
    return ev["time"] + tp + RETARDO_DISPARO_S + latencia


# ---------------------------------------------------------------- clasificación


def clasificar(evs, obs, aviso_de, umbral, falsas_sin_sismo=0):
    """Cuenta aciertos, tardes, perdidos, falsas y correctos para un umbral de MMI.

    aviso_de(ev) devuelve la hora del aviso a Medellín para ese sismo, o None.
    """
    k = {"TP": 0, "tarde": 0, "FN": 0, "FP": falsas_sin_sismo, "TN": 0, "aviso_s": []}
    for ev in evs:
        o = obs.get(clave(ev))
        if not o or "error" in o:
            continue
        t = aviso_de(ev)
        cruce = o["cruces"].get(str(umbral))
        if o["ruido_mmi"] >= umbral:
            continue  # el ruido de HEL ya estaba por encima: no se puede juzgar
        if cruce:
            cruce = UTCDateTime(cruce)
            if t is None:
                k["FN"] += 1
            elif t < cruce:
                k["TP"] += 1
                k["aviso_s"].append(cruce - t)
            else:
                k["tarde"] += 1
                k["aviso_s"].append(cruce - t)
        else:
            k["FP" if t is not None else "TN"] += 1
    return k


def fila(nombre, k):
    a = sorted(x for x in k["aviso_s"] if x > 0)
    med = f"{statistics.median(a):5.0f}" if a else "    -"
    return (f"  {nombre:34} {k['TP']:4} {k['tarde']:6} {k['FN']:5} {k['FP']:6} {k['TN']:6}"
            f"   {med}")


CABEZA = (f"  {'':34} {'TP':>4} {'tarde':>6} {'FN':>5} {'FP':>6} {'TN':>6}   aviso (mediana, s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("registro")
    ap.add_argument("--catalogos", required=True, help="pickle de catálogos (evaluar_asociador --cache)")
    ap.add_argument("--obs", help="caché de intensidades en HEL (json)")
    ap.add_argument("--repasos", help="caché de los repasos de los asociadores (pickle)")
    ap.add_argument("--latencia", type=float, default=15.0)
    ap.add_argument("--csv", help="detalle por sismo")
    args = ap.parse_args()

    picks = load_picks(args.registro)
    start, end = picks[0][0] - 600, picks[-1][0] + 600
    cats = pickle.load(open(args.catalogos, "rb"))
    todos = [e for evs in cats.values() for e in evs]
    unicos = eventos(cats, start, end)
    print(f"{len(picks)} disparos, {len(unicos)} sismos de catálogo, {start.date} a {end.date}, "
          f"latencia {args.latencia:.0f} s")

    if args.repasos and os.path.exists(args.repasos):
        repasos = pickle.load(open(args.repasos, "rb"))
    else:
        repasos = {"ventana": repasar(Associator, picks),
                   "bayesiano": repasar(BayesAssociator, picks, malla=Malla())}
        if args.repasos:
            pickle.dump(repasos, open(args.repasos, "wb"))
    resultado = {n: avisos(r, todos, unicos, args.latencia) for n, r in repasos.items()}

    explicados = set().union(*(set(p) for p, _ in resultado.values()))
    medir_ev = [e for e in unicos
                if clave(e) in explicados
                or intensidad.mmi_prevista(e["mag"], rhyp(e, *SITIO))[0] >= MMI_PREVISTA_MIN]
    obs = medir(medir_ev, args.obs)
    validos = [e for e in medir_ev if "error" not in obs[clave(e)]]
    print(f"intensidad medida en HEL para {len(validos)} sismos "
          f"({len(medir_ev) - len(validos)} sin datos); el resto se da por no sentido")
    altos = sorted(validos, key=lambda e: -obs[clave(e)]["mmi"])
    for u in UMBRALES:
        n = sum(1 for e in validos if obs[clave(e)]["cruces"][str(u)])
        print(f"  sismos que superaron MMI {u:g} en HEL: {n}")
    print("  los de mayor intensidad:")
    for e in altos[:8]:
        o = obs[clave(e)]
        m, s = intensidad.mmi_prevista(e["mag"], rhyp(e, *SITIO))
        print(f"    MMI {o['mmi']:.1f} (prevista {m:.1f}, ruido {o['ruido_mmi']:.1f}) "
              f"PGA {o['pga_cms2']:.2f} cm/s² — M{e['mag']} {e['place']} {str(e['time'])[:16]}"
              f"{' SATURADA' if o['saturada'] else ''}")

    # Los sismos que no se midieron se cuentan como no sentidos (TN o FP)
    no_medidos = [e for e in unicos if clave(e) not in obs]
    for e in no_medidos:
        obs[clave(e)] = {"mmi": 1.0, "ruido_mmi": 0.0, "cruces": {str(u): None for u in UMBRALES},
                         "supuesto": True}

    for u in UMBRALES:
        print(f"\n===== Umbral MMI {u:g} en Medellín (HEL) =====")
        print("Opción A — el sistema como está (aviso = nivel de la detección):")
        print(CABEZA)
        for n, (por_sismo, sin_sismo) in resultado.items():
            for pol, niveles in POLITICAS.items():
                falsas = sum(1 for p in sin_sismo if hora_aviso(p, niveles))
                k = clasificar(unicos, obs, lambda e: hora_aviso(por_sismo.get(clave(e), {}), niveles),
                               u, falsas)
                print(fila(f"{n}, {pol}", k))
        print(f"Opción B — cota ideal (sismo del catálogo conocido al detectar; aviso si P > p*):")
        print(CABEZA)
        for p in P_ESTRELLA:
            variantes = [(n, por_sismo) for n, (por_sismo, _) in resultado.items()]
            for n, por_sismo in variantes + [("red ideal", None)]:
                def aviso(e, por_sismo=por_sismo):
                    m, s = intensidad.mmi_prevista(e["mag"], rhyp(e, *SITIO))
                    if intensidad.prob_excedencia(m, s, u) <= p:
                        return None
                    if por_sismo is None:
                        return red_ideal(e, args.latencia)
                    return hora_aviso(por_sismo.get(clave(e), {}), POLITICAS["cualquier nivel"])
                print(fila(f"p*={p:g}, {n}", clasificar(unicos, obs, aviso, u)))

    # Sesgo de la ecuación de intensidad en HEL (para calibrarla después)
    res = [obs[clave(e)]["mmi"] - intensidad.mmi_prevista(e["mag"], rhyp(e, *SITIO))[0]
           for e in validos if obs[clave(e)]["mmi"] > obs[clave(e)]["ruido_mmi"] + 0.5]
    if res:
        print(f"\nMMI observada − prevista en HEL (sismos sobre el ruido, n={len(res)}): "
              f"mediana {statistics.median(res):+.2f}, desviación {statistics.pstdev(res):.2f}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["sismo", "hora", "mag", "lugar", "rhyp_km", "mmi_prevista", "mmi_hel",
                        "ruido", "pga_cms2", "cruce_mmi2", "cruce_mmi3",
                        *(f"aviso_{n}_{lv}" for n in resultado for lv in ("alta", "media", "baja")),
                        "aviso_red_ideal"])
            for e in validos:
                o = obs[clave(e)]
                r = rhyp(e, *SITIO)
                w.writerow([clave(e), str(e["time"])[:19], e["mag"], e["place"], round(r),
                            round(intensidad.mmi_prevista(e["mag"], r)[0], 2), o["mmi"],
                            o["ruido_mmi"], o["pga_cms2"], o["cruces"]["2.0"], o["cruces"]["3.0"],
                            *(str(resultado[n][0].get(clave(e), {}).get(lv) or "")
                              for n in resultado for lv in ("alta", "media", "baja")),
                            str(red_ideal(e, args.latencia))])
        print(f"detalle: {args.csv}")


if __name__ == "__main__":
    main()
