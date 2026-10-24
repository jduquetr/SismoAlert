"""Lote histórico para la evaluación: sismos sentidos en Medellín desde que existe HEL.

1. catalogo: sismos del USGS (M ≥ 3,5 a menos de 1.000 km de Medellín) y, para los locales
   pequeños, del SGC (M ≥ 2,5 a menos de 150 km), desde junio de 2011.
2. seleccionar: se mide la intensidad (observado.py) de los candidatos, los sismos a los que
   la ecuación de intensidad da al menos MMI 1 en HEL. Entran todos los que llegaron a MMI 2
   en HEL, todos los no sentidos a los que la ecuación les daba MMI ≥ 1,5 (donde se juegan las
   falsas alertas) y una muestra al azar del resto, del mismo tamaño que los sentidos.

Luego se repasan con señal y se evalúan:

  python -m evaluacion.lote_historico catalogo --salida lote/cat.pickle
  python -m evaluacion.lote_historico seleccionar --catalogos lote/cat.pickle --obs lote/obs.json --salida lote/sismos.pickle
  python -m evaluacion.repaso senal lote/sismos.pickle --salida lote/decisiones.jsonl
  python -m evaluacion.evaluar --decisiones lote/decisiones.jsonl --catalogos lote/cat.pickle --universo lote/sismos.pickle --obs lote/obs.json

Ojo: se repasa con las estaciones de hoy (config.STATIONS); en años pasados algunas no
existían o no tenían datos, y simplemente no participan.
"""
import argparse
import pickle
import random
import sys

from obspy import UTCDateTime

import config
import intensidad
import sources

from . import catalogo, observado

DESDE = UTCDateTime("2011-06-18")  # inicio de CM.HEL
USGS_MAG, USGS_RADIO_KM = 3.5, 1000
SGC_MAG, SGC_RADIO_KM = 2.5, 150
MMI_CANDIDATO = 1.0
MMI_SENTIDO = 2.0
MMI_DUDOSO = 1.5


def bajar_catalogo(desde, hasta):
    cats = {"USGS": catalogo.usgs_historico(desde, hasta, USGS_MAG, USGS_RADIO_KM), "SGC": []}
    t = desde
    while t < hasta:
        t2 = min(t + 28 * 86400, hasta)
        try:
            evs = catalogo.con_reintentos(lambda: sources.sgc_biweekly(t, t2))
        except Exception as err:
            print(f"  SGC {t.date}: {err}", file=sys.stderr)
            evs = []
        cats["SGC"] += [e for e in evs if (e.get("mag") or 0) >= SGC_MAG and sources.distance_km(
            *config.MEDELLIN, e["lat"], e["lon"]) <= SGC_RADIO_KM]
        print(f"  SGC hasta {t2.date}: {len(cats['SGC'])} sismos", file=sys.stderr)
        t = t2
    return cats


def prevista_hel(ev):
    return intensidad.mmi_prevista(ev["mag"], catalogo.rhyp(ev, *config.STATIONS[observado.MEDELLIN][3:5]))[0]


def seleccionar(cats, obs_path, semilla=1):
    unicos = catalogo.eventos(cats)
    cand = [e for e in unicos if prevista_hel(e) >= MMI_CANDIDATO]
    print(f"{len(unicos)} sismos únicos, {len(cand)} candidatos (MMI prevista en HEL ≥ "
          f"{MMI_CANDIDATO:g})", file=sys.stderr)
    obs = observado.medir(cand, obs_path)

    def mmi_hel(e):
        o = observado.de_sitio(obs, e, observado.MEDELLIN)
        return o["mmi"] if o and o["ruido_mmi"] < MMI_SENTIDO else None

    medidos = [e for e in cand if mmi_hel(e) is not None]
    sentidos = [e for e in medidos if mmi_hel(e) >= MMI_SENTIDO]
    dudosos = [e for e in medidos if mmi_hel(e) < MMI_SENTIDO and prevista_hel(e) >= MMI_DUDOSO]
    resto = [e for e in medidos if e not in sentidos and e not in dudosos]
    muestra = random.Random(semilla).sample(resto, min(len(sentidos), len(resto)))
    print(f"medidos {len(medidos)}: sentidos {len(sentidos)}, no sentidos con MMI prevista ≥ "
          f"{MMI_DUDOSO:g} {len(dudosos)}, muestra del resto {len(muestra)}", file=sys.stderr)
    for e in sorted(sentidos, key=lambda e: -mmi_hel(e))[:15]:
        print(f"  MMI {mmi_hel(e):.1f} (prevista {prevista_hel(e):.1f}) M{e['mag']} "
              f"{e['place']} {str(e['time'])[:16]}", file=sys.stderr)
    return sorted(sentidos + dudosos + muestra, key=lambda e: e["time"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paso", choices=("catalogo", "seleccionar"))
    ap.add_argument("--catalogos")
    ap.add_argument("--obs")
    ap.add_argument("--salida", required=True)
    ap.add_argument("--desde", default=str(DESDE))
    ap.add_argument("--hasta", default=None)
    args = ap.parse_args()
    if args.paso == "catalogo":
        cats = bajar_catalogo(UTCDateTime(args.desde),
                              UTCDateTime(args.hasta) if args.hasta else UTCDateTime())
        pickle.dump(cats, open(args.salida, "wb"))
    else:
        sel = seleccionar(catalogo.cargar(args.catalogos), args.obs)
        pickle.dump(sel, open(args.salida, "wb"))
        print(f"{len(sel)} sismos -> {args.salida}", file=sys.stderr)


if __name__ == "__main__":
    main()
