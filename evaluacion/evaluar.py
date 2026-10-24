"""Juzga la alerta con las métricas de Meier (2017), a partir de su registro de decisiones.

Entradas: uno o más registros de decisiones (datos/decisiones.jsonl del servidor, o los que
escribe evaluacion/repaso.py), los catálogos del periodo y la intensidad observada en cada
sitio (observado.py, se mide y se guarda en caché). No importa ni ejecuta la alerta.

Para cada sismo, sitio y umbral de intensidad se decide si hubo alerta y cuándo, de cuatro
maneras:

- "sistema": la alerta como está, solo para Medellín: avisa toda decisión de nivel alta o
  media (o de cualquier nivel). No dice cuánto va a temblar.
- "magnitud del sistema" (el SPS del artículo): con la magnitud y la ubicación que la alerta
  tenía en cada decisión se predice la MMI del sitio (Allen, Wald y Worden, 2012) y se avisa
  la primera vez que P(MMI > umbral) > p*. Solo con el asociador bayesiano y magnitud.
- "catálogo" (el IFS, cota ideal): en la primera decisión se supone conocido el sismo del
  catálogo (magnitud y foco).
- "red ideal": como "catálogo", pero la detección llega con la P teórica a la estación más
  cercana que vota: lo máximo que daría esta red.

Las decisiones de origen "repaso" no traen latencia: se evalúan sin latencia y con
--latencia (16 s por omisión: la mediana medida en HEL, 4 s de llenado del paquete y 12 de
viaje). Las de origen "vivo" ya la traen.
Las detecciones sin sismo de catálogo se cuentan aparte, como en el artículo.

Uso:
  python -m evaluacion.evaluar --decisiones D.jsonl [D2.jsonl ...] --catalogos cat.pickle
      [--universo sismos.pickle] [--obs obs.json] [--latencia 16] [--csv salida.csv]
"""
import argparse
import csv
import json
import math
import pickle

from obspy import UTCDateTime

import config
import intensidad
import sources

from . import catalogo, metricas, observado
from .catalogo import clave

UMBRALES = (2.0, 3.0, 4.0)
P_ESTRELLA = (0.1, 0.3, 0.5, 0.7)
P_ESTRELLA_TEXTO = (0.3, 0.5)  # las que se imprimen; el CSV lleva todas
POLITICAS = {"alta o media": ("alta", "media"), "cualquier nivel": ("alta", "media", "baja")}
TOL = 0.5
# La red ideal es una cota: la P teórica a la estación más cercana, sin el retardo medio del
# disparo STA/LTA (~3 s). Con ese retardo, la detección real le ganaba en varios sismos
RETARDO_DISPARO_S = 0.0
SIGMA_MAG_DEFECTO = 0.3
MEDELLIN = observado.MEDELLIN


def leer_decisiones(paths):
    lineas = []
    for p in paths:
        for line in open(p, encoding="utf-8"):
            if line.strip():
                d = json.loads(line)
                d["emitida"] = UTCDateTime(d["emitida"])
                lineas.append(d)
    return lineas


def historias(lineas):
    """{(asociador, sismo repasado, id): [decisiones en orden]}."""
    h = {}
    for d in lineas:
        if d.get("nivel") == "catálogo":
            continue  # avisos de EMSC sin estaciones: no son decisiones de la red
        h.setdefault((d["asociador"], d.get("sismo_repasado", ""), d["id"]), []).append(d)
    for v in h.values():
        v.sort(key=lambda d: d["emitida"])
    return h


class Evaluacion:
    def __init__(self, lineas, todos, unicos, universo, obs):
        self.unicos, self.universo, self.obs = unicos, universo, obs
        self.sitios = observado.sitios()
        self._cache = {}
        self.por_evento = {}   # asociador -> {sismo: [decisiones]}
        self.falsas = {}       # asociador -> [[decisiones]] sin sismo
        for (asoc, _, _), hist in historias(lineas).items():
            ev = catalogo.emparejar(hist[-1], todos)
            ev = catalogo.canonico(ev, unicos) if ev else None
            if ev is None:
                self.falsas.setdefault(asoc, []).append(hist)
            else:
                self.por_evento.setdefault(asoc, {}).setdefault(clave(ev), []).extend(hist)
        for d in self.por_evento.values():
            for v in d.values():
                v.sort(key=lambda x: x["emitida"])
        self.asociadores = sorted(set(self.por_evento) | set(self.falsas))

    @staticmethod
    def _lat(d, lat):
        return 0.0 if d.get("origen") == "vivo" else lat

    # --- hora de la alerta para un sitio, según cada manera de decidir

    def t_sistema(self, asoc, ev, niveles, lat):
        ts = [d["emitida"] + self._lat(d, lat) for d in self.por_evento.get(asoc, {}).get(clave(ev), [])
              if d["nivel"] in niveles]
        return min(ts) if ts else None

    def prediccion_sistema(self, d, sitio):
        mag, loc = d.get("magnitud"), d.get("ubicacion")
        if not mag or not loc or mag.get("valor") is None:
            return None
        lat, lon = self.sitios[sitio][3:5]
        r = math.hypot(sources.distance_km(lat, lon, loc["lat"], loc["lon"]), loc.get("depth") or 10)
        return intensidad.mmi_prevista(mag["valor"], r, mag.get("incertidumbre") or SIGMA_MAG_DEFECTO)

    def t_magnitud(self, asoc, ev, sitio, umbral, p, lat):
        for d in self.por_evento.get(asoc, {}).get(clave(ev), []):
            pr = self.prediccion_sistema(d, sitio)
            if pr and intensidad.prob_excedencia(*pr, umbral) > p:
                return d["emitida"] + self._lat(d, lat)
        return None

    def prediccion_catalogo(self, ev, sitio):
        k = (clave(ev), sitio)
        if k not in self._cache:
            self._cache[k] = intensidad.mmi_prevista(ev["mag"],
                                                     catalogo.rhyp(ev, *self.sitios[sitio][3:5]))
        return self._cache[k]

    def t_catalogo(self, asoc, ev, sitio, umbral, p, lat):
        hist = self.por_evento.get(asoc, {}).get(clave(ev), [])
        if hist and intensidad.prob_excedencia(*self.prediccion_catalogo(ev, sitio), umbral) > p:
            return hist[0]["emitida"] + self._lat(hist[0], lat)
        return None

    def t_red_ideal(self, ev, sitio, umbral, p, lat):
        if intensidad.prob_excedencia(*self.prediccion_catalogo(ev, sitio), umbral) <= p:
            return None
        k = clave(ev)
        if k not in self._cache:
            self._cache[k] = min(catalogo.tiempo_p(ev, *v[3:5]) for v in config.STATIONS.values())
        return ev["time"] + self._cache[k] + RETARDO_DISPARO_S + lat

    def con_magnitud(self, asoc):
        return any(d.get("magnitud") for v in self.por_evento.get(asoc, {}).values() for d in v)

    # --- clasificación

    def clases(self, t_alerta, sitios, umbral, tol=TOL):
        out = []
        for ev in self.universo:
            for s in sitios:
                out.append(metricas.clasificar(observado.de_sitio(self.obs, ev, s),
                                               t_alerta(ev, s), umbral, tol))
        return out

    def variantes(self, lat, sitios):
        """(nombre, asociador, p*, función t_alerta(ev, sitio)) para estos sitios."""
        v = []
        for asoc in self.asociadores:
            if sitios == [MEDELLIN]:
                for pol, niveles in POLITICAS.items():
                    v.append((f"sistema, {pol}", asoc, None,
                              lambda ev, s, a=asoc, n=niveles: self.t_sistema(a, ev, n, lat)))
        for p in P_ESTRELLA:
            for asoc in self.asociadores:
                if self.con_magnitud(asoc):
                    v.append(("magnitud del sistema", asoc, p, lambda ev, s, a=asoc, p=p:
                              self.t_magnitud(a, ev, s, self._umbral, p, lat)))
            for asoc in self.asociadores:
                v.append(("catálogo (ideal)", asoc, p, lambda ev, s, a=asoc, p=p:
                          self.t_catalogo(a, ev, s, self._umbral, p, lat)))
            v.append(("red ideal", "-", p, lambda ev, s, p=p: self.t_red_ideal(ev, s, self._umbral, p, lat)))
        return v

    def tabla(self, lat, sitios, filas_csv, nombre_sitio):
        for umbral in UMBRALES:
            self._umbral = umbral
            print(f"\n  -- umbral MMI {umbral:g}, tolerancia ±{TOL} --")
            print(metricas.CABEZA)
            for nombre, asoc, p, f in self.variantes(lat, sitios):
                for tol in (TOL, 0.0):
                    k = metricas.resumen(self.clases(f, sitios, umbral, tol))
                    filas_csv.append({"latencia_s": lat, "sitio": nombre_sitio, "umbral": umbral,
                                      "tolerancia": tol, "manera": nombre, "asociador": asoc,
                                      "p_estrella": p, **{x: k[x] for x in (
                                          "TP", "FN", "tarde", "FP", "TN", "TPR", "FPR", "CAR",
                                          "aviso_mediana")}})
                    if tol == TOL and (p is None or p in P_ESTRELLA_TEXTO):
                        etiqueta = f"{nombre}, {asoc}" + (f", p*={p:g}" if p is not None else "")
                        print(metricas.fila(etiqueta, k))

    def falsas_detecciones(self, lineas):
        vivas = [d["emitida"] for d in lineas if d.get("origen") == "vivo"]
        dias = (max(vivas) - min(vivas)) / 86400 if len(vivas) > 1 else None
        print("\nDetecciones sin sismo de catálogo (falsas detecciones, aparte de la clasificación):")
        for asoc in self.asociadores:
            for pol, niveles in POLITICAS.items():
                n = sum(1 for h in self.falsas.get(asoc, []) if any(d["nivel"] in niveles for d in h))
                extra = f" ({n / dias:.1f} por día)" if dias else ""
                print(f"  {asoc}, {pol}: {n}{extra}")

    def error_prediccion(self, lat):
        """ΔMMI frente al tiempo de aviso, en todos los sitios con medida."""
        for asoc in self.asociadores:
            for manera in ("magnitud del sistema", "catálogo (ideal)"):
                if manera == "magnitud del sistema" and not self.con_magnitud(asoc):
                    continue
                muestras = []
                for ev in self.universo:
                    hist = self.por_evento.get(asoc, {}).get(clave(ev), [])
                    if not hist:
                        continue
                    for s, v in self.sitios.items():
                        o = observado.de_sitio(self.obs, ev, s)
                        if not o:
                            continue
                        cruce = o["cruces"].get("2.0")
                        ref = UTCDateTime(cruce) if cruce else \
                            ev["time"] + 1.75 * catalogo.tiempo_p(ev, *v[3:5])
                        usar = hist if manera == "magnitud del sistema" else hist[:1]
                        for d in usar:
                            pr = (self.prediccion_sistema(d, s) if manera == "magnitud del sistema"
                                  else self.prediccion_catalogo(ev, s))
                            if pr:
                                t = d["emitida"] + self._lat(d, lat)
                                # La MMI observada no baja de 1 (ShakeMap): la prevista tampoco
                                muestras.append((o["mmi"], ref - t, o["mmi"] - max(pr[0], 1.0)))
                print(f"\nΔMMI (observada − predicha) por tiempo de aviso, {manera}, {asoc}, "
                      f"todos los sitios ({len(muestras)} predicciones). Aviso hasta el cruce de "
                      f"MMI 2 o, si no se cruzó, hasta la S teórica:")
                print(metricas.tabla_error(muestras))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decisiones", nargs="+", required=True)
    ap.add_argument("--catalogos", required=True, help="pickle {SGC|USGS|EMSC: [sismos]}")
    ap.add_argument("--universo", help="pickle con la lista de sismos a clasificar (por omisión "
                                       "todos los del periodo de las decisiones)")
    ap.add_argument("--obs", help="caché de intensidades observadas (json)")
    ap.add_argument("--latencia", type=float, default=16.0)
    ap.add_argument("--sin-medir", action="store_true", help="no bajar señal nueva")
    ap.add_argument("--csv")
    args = ap.parse_args()

    lineas = leer_decisiones(args.decisiones)
    cats = catalogo.cargar(args.catalogos)
    todos = [e for evs in cats.values() for e in evs]
    disparos = [UTCDateTime(d["primer_disparo"]) for d in lineas if d.get("nivel") != "catálogo"]
    start, end = min(disparos) - 900, max(disparos) + 60
    unicos = catalogo.eventos(cats)
    if args.universo:
        universo = [catalogo.canonico(e, unicos) or e for e in pickle.load(open(args.universo, "rb"))]
    else:
        universo = [e for e in unicos if start <= e["time"] <= end]
    ev_ = Evaluacion(lineas, todos, unicos, universo, {})

    # Se mide la intensidad de los sismos que alguna decisión explica o que la ecuación no da
    # por imperceptibles en algún sitio; el resto se toma como no sentido
    explicados = {k for d in ev_.por_evento.values() for k in d}
    medir = [e for e in universo if args.universo or clave(e) in explicados or max(
        ev_.prediccion_catalogo(e, s)[0] for s in ev_.sitios) >= 1.0]
    obs = observado.medir([] if args.sin_medir else medir, args.obs)
    ev_.obs = obs
    origenes = sorted({d.get("origen") for d in lineas})
    latencias = (0.0,) if origenes == ["vivo"] else (0.0, args.latencia)
    print(f"{len(lineas)} decisiones ({', '.join(origenes)}) de {', '.join(ev_.asociadores)}; "
          f"{len(universo)} sismos a clasificar, {sum(1 for e in universo if clave(e) in obs)} con "
          f"intensidad medida; {start.date} a {end.date}")
    for u in UMBRALES:
        n = sum(1 for e in universo if (observado.de_sitio(obs, e, MEDELLIN) or {}).get("mmi", 0) >= u)
        print(f"  sismos que llegaron a MMI {u:g} en Medellín (HEL): {n}")

    ev_.falsas_detecciones(lineas)
    filas = []
    for lat in latencias:
        print(f"\n===== Latencia {lat:.0f} s — Medellín (HEL) =====")
        ev_.tabla(lat, [MEDELLIN], filas, "Medellín")
        print(f"\n===== Latencia {lat:.0f} s — todos los sitios ({len(ev_.sitios)} estaciones) =====")
        ev_.tabla(lat, list(ev_.sitios), filas, "todos")
    ev_.error_prediccion(latencias[-1])
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(filas[0]))
            w.writeheader()
            w.writerows(filas)
        print(f"\ndetalle: {args.csv}")


if __name__ == "__main__":
    main()
