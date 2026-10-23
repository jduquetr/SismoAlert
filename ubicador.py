"""Ubicador bayesiano de sismos a partir de los disparos de las estaciones.

Adapta a nuestra red el método IPF de la agencia meteorológica de Japón (Tamaribuchi,
Yamada y Wu, 2014, Zisin 67; en operación desde 2016, ver Kodera et al., 2021). En vez de
aceptar que todo disparo dentro de una ventana de tiempo es del mismo sismo, se busca el
epicentro más probable dados:

- dónde ha temblado antes (probabilidad de partida, sismicidad_previa.json);
- que la primera estación en disparar suele ser la más cercana (zona de Voronoi ampliada);
- los tiempos de los disparos frente a los tiempos de viaje de la onda P (tiempos_p.json);
- las estaciones cercanas que siguen calladas cuando la onda ya debió llegarles (la idea
  del método "llegó / no llegó", NYAD).

Cada término tiene un piso para los datos que no encajan, más alto para las estaciones
lejanas: un disparo de ruido no arrastra la solución. Con eso se puede decir si un disparo
nuevo lo explica un sismo en curso (Ubicacion.explica) o si es de otro sismo o ruido.

Diferencias con el original, por ser una red de ~10 estaciones a cientos de km entre sí en
vez de ~1.000 a decenas de km: búsqueda en una malla fija de 0,2° en lugar de filtro de
partículas (con tan pocas estaciones es exacta y tarda milisegundos), errores de tiempo de
~4 s en vez de 1,5 s (disparos STA/LTA y modelo 1D) y zona de Voronoi más ancha. Todavía no
usa amplitudes: el registro solo guarda la relación STA/LTA, que depende del ruido de cada
estación. Eso queda para cuando se mida la amplitud en unidades físicas.
"""
import json
import math
from pathlib import Path

import numpy as np

import config

HERE = Path(__file__).parent
KM_PER_DEG = 111.195
EPS = 1e-12


def _distance_km(lat, lon, lat0, lon0):
    """Distancia epicentral (km) de cada nodo de la malla a un punto, en esfera."""
    p1, p2 = np.radians(lat), math.radians(lat0)
    dl = np.radians(lon - lon0)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * math.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


class TiemposP:
    """Tiempo de la primera onda P (IASP91), interpolado en distancia y profundidad."""

    def __init__(self, path=HERE / "tiempos_p.json"):
        t = json.loads(Path(path).read_text(encoding="utf-8"))
        self.dist = np.array(t["distancias_km"], dtype=float)
        self.depth = np.array(t["profundidades_km"], dtype=float)
        self.table = np.array(t["tiempos_s"], dtype=float)

    def __call__(self, dist_km, depth_km):
        d = np.clip(dist_km, self.dist[0], self.dist[-1])
        z = np.clip(depth_km, self.depth[0], self.depth[-1])
        i = np.clip(np.searchsorted(self.depth, z) - 1, 0, len(self.depth) - 2)
        j = np.clip(np.searchsorted(self.dist, d) - 1, 0, len(self.dist) - 2)
        fz = (z - self.depth[i]) / (self.depth[i + 1] - self.depth[i])
        fd = (d - self.dist[j]) / (self.dist[j + 1] - self.dist[j])
        t = self.table
        return ((1 - fz) * ((1 - fd) * t[i, j] + fd * t[i, j + 1])
                + fz * ((1 - fd) * t[i + 1, j] + fd * t[i + 1, j + 1]))


class Malla:
    """Epicentros posibles en la región, con su probabilidad de partida."""

    def __init__(self, stations=None, step=None, depths=None):
        self.stations = stations or config.STATIONS
        step = step or config.UBICADOR_PASO_GRADOS
        depths = np.array(depths or config.UBICADOR_PROFUNDIDADES_KM, dtype=float)
        r = config.REGION
        lats = np.arange(r["minlat"], r["maxlat"] + 1e-9, step)
        lons = np.arange(r["minlon"], r["maxlon"] + 1e-9, step)
        la, lo, de = np.meshgrid(lats, lons, depths, indexing="ij")
        self.lat, self.lon, self.depth = la.ravel(), lo.ravel(), de.ravel()
        self.tp = TiemposP()
        self.log_prior = self._log_prior()
        self._dist, self._tt = {}, {}

    def _log_prior(self):
        """Sismicidad histórica por celda: log((min(n, 100) + 1) / 101), como en el artículo.

        El tope en 100 evita que un enjambre o una secuencia de réplicas domine; el +1 deja
        posible cualquier sitio, aunque nunca haya temblado ahí. Se multiplica por
        UBICADOR_PESO_PREVIA: con pocas estaciones, a peso completo pesaba más que los datos
        (un disparo de ruido en PRV llevaba el epicentro de Chaparral a Panamá).
        """
        path = HERE / "sismicidad_previa.json"
        if not path.exists():
            return np.zeros_like(self.lat)
        s = json.loads(path.read_text(encoding="utf-8"))
        counts = {(i, j, k): n for i, j, k, n in s["celdas"]}
        lat0, lon0 = s["origen"]
        i = ((self.lat - lat0) // s["celda_grados"]).astype(int)
        j = ((self.lon - lon0) // s["celda_grados"]).astype(int)
        k = (self.depth // s["celda_km"]).astype(int)
        n = np.array([counts.get(c, 0) for c in zip(i, j, k)], dtype=float)
        return config.UBICADOR_PESO_PREVIA * np.log((np.minimum(n, 100) + 1) / 101)

    def dist(self, sta):
        if sta not in self._dist:
            lat, lon = self.stations[sta][3:5]
            self._dist[sta] = _distance_km(self.lat, self.lon, lat, lon).astype(np.float32)
        return self._dist[sta]

    def tt(self, sta):
        if sta not in self._tt:
            self._tt[sta] = self.tp(self.dist(sta), self.depth).astype(np.float32)
        return self._tt[sta]


def _robust_log(r, sigma, g0):
    """log de una normal con piso g0 para datos anómalos (ec. 8 del artículo)."""
    return np.log((1 - g0) * np.exp(-0.5 * (r / sigma) ** 2) + g0 + EPS)


def _g0(rank):
    """Piso según qué tan lejos está la estación (1 = la más cercana al epicentro probado).

    La más cercana no tiene piso: su tiempo tiene que encajar. Para las lejanas el piso sube
    y un disparo raro allá pesa menos (ec. 9 del artículo). Con tope: en el original el piso
    llega a 1 porque hay cientos de estaciones; aquí, con ~10, un disparo que no encaja
    tiene que seguir costando o la sismicidad previa decide sola.
    """
    return config.UBICADOR_PISO_MAX * (1 - np.exp(-(rank - 1) / config.UBICADOR_C2))


class Ubicacion:
    """Resultado del ubicador: el epicentro más probable y la nube de epicentros posibles."""

    def __init__(self, malla, ref, idx, w, t0, best, residuals, mag=None):
        self.malla = malla
        self.ref = ref            # UTCDateTime de referencia (primer disparo)
        self.idx, self.w, self.t0 = idx, w, t0  # nodos con peso, sus pesos y orígenes (s)
        b = best
        self.lat, self.lon = float(malla.lat[b]), float(malla.lon[b])
        self.depth = float(malla.depth[b])
        self.origin = ref + float(t0[np.searchsorted(idx, b)])
        self.residuals = residuals  # estación -> residuo (s) en el mejor epicentro
        # Término de amplitud: (Magnitud, magnitud del sismo en cada nodo con peso, residuos
        # de magnitud en el mejor epicentro {estación: (residuo, completa)}), o None
        self.mag = mag
        self.magnitude = None
        if mag:
            self.magnitude = float(mag[1][np.searchsorted(idx, b)])
        d = _distance_km(malla.lat[idx], malla.lon[idx], self.lat, self.lon)
        self.uncertainty_km = float(np.sqrt(np.sum(w * d ** 2)))

    def explica(self, sta, onset, amps=None, complete=False):
        """Probabilidad de que un disparo en `sta` a la hora `onset` sea de este sismo.

        Suma el peso de los epicentros posibles cuya onda P llega a esa estación dentro de
        ±A·σ del disparo y, si hay amplitudes, cuya magnitud encaja con la del disparo
        (ec. 17-20 del artículo). Mientras la ventana de amplitud no termina (complete=False)
        solo cuenta si el disparo ya es demasiado fuerte para el sismo.
        """
        if sta not in self.malla.stations:
            return 0.0
        pred = self.t0 + self.malla.tt(sta)[self.idx]
        ok = np.abs((onset - self.ref) - pred) <= config.UBICADOR_A * config.UBICADOR_SIGMA_S
        if self.mag and amps:
            m = _station_magnitude(self.mag[0], self.malla, sta, amps, self.idx)
            if m is not None:
                r = m - self.mag[1]
                ok &= (np.abs(r) if complete else r) <= config.UBICADOR_A * config.UBICADOR_SIGMA_M
        return float(np.sum(self.w[ok]))

    def fits(self, stations=None):
        """Estaciones cuyo disparo encaja (±A·σ) con el mejor epicentro, en tiempo y, si hay
        amplitudes, en magnitud."""
        lim = config.UBICADOR_A * config.UBICADOR_SIGMA_S
        lim_m = config.UBICADOR_A * config.UBICADOR_SIGMA_M
        mres = self.mag[2] if self.mag else {}

        def mag_ok(s):
            if s not in mres:
                return True
            r, complete = mres[s]
            return (abs(r) if complete else r) <= lim_m

        return [s for s, r in self.residuals.items()
                if abs(r) <= lim and mag_ok(s) and (stations is None or s in stations)]

    def to_dict(self):
        return {"lat": round(self.lat, 2), "lon": round(self.lon, 2), "depth": self.depth,
                "origin": str(self.origin),
                "incertidumbre_km": round(self.uncertainty_km),
                "residuos_s": {s: round(r, 1) for s, r in self.residuals.items()},
                **({"residuos_m": {s: round(r, 1) for s, (r, _) in self.mag[2].items()}}
                   if self.mag else {})}


def _station_magnitude(mag, malla, sta, amps, idx=None):
    """Magnitud que da la amplitud de `sta` (ventana de 5 s, la del IPF) para cada nodo."""
    w = 5
    tipo = mag.tipo(amps, w)
    k = mag.coef.get(tipo, {}).get(w)
    a = amps.get(tipo, {}).get(w, 0)
    if k is None or sta not in mag.sens or a <= 0:
        return None
    d = malla.dist(sta) if idx is None else malla.dist(sta)[idx]
    z = malla.depth if idx is None else malla.depth[idx]
    r = np.maximum(np.hypot(d, z), 1.0)
    return (k["a"] * np.log10(a / mag.sens[sta]) + k["b"] * np.log10(r) + k["c"]
            + k["correccion"].get(sta, 0.0))


def ubicar(malla, picks, now, alive=None, weak=(), amps=None, mag=None):
    """Ubica un sismo a partir de sus disparos.

    picks: {estación: UTCDateTime del disparo}. now: hora a la que se evalúa (sirve para
    saber qué estaciones calladas ya debieron disparar). alive: estaciones que están
    enviando datos (por defecto todas las de la malla). weak: estaciones con disparo débil
    (STA/LTA < MIN_RATIO), que suelen ser ruido: casi no mueven la solución.
    amps: {estación: (amplitudes como magnitud.medir, ventana de 5 s completa)} y mag: un
    magnitud.Magnitud, para el término de amplitud (config.UBICADOR_AMPLITUD).
    """
    picks = {s: t for s, t in picks.items() if s in malla.stations}
    if not picks:
        return None
    strong = [s for s in picks if s not in weak] or list(picks)
    alive = [s for s in (alive or malla.stations) if s in malla.stations]
    first = min(picks, key=picks.get)
    ref = picks[first]
    sts = sorted(set(alive) | set(picks))
    D = np.stack([malla.dist(s) for s in sts])
    # rank[k, n] = 1 si la estación k es la más cercana al nodo n, 2 la segunda...
    rank = np.empty_like(D, dtype=np.int16)
    rank[np.argsort(D, axis=0), np.arange(D.shape[1])] = np.arange(1, len(sts) + 1)[:, None]
    row = {s: k for k, s in enumerate(sts)}

    sigma = config.UBICADOR_SIGMA_S
    obs = np.array([picks[s] - ref for s in picks])[:, None]
    tt = np.stack([malla.tt(s) for s in picks])
    t0 = np.median(obs - tt, axis=0)  # hora de origen de cada nodo, robusta a un disparo raro
    lp = malla.log_prior.copy()
    for k, s in enumerate(picks):
        g0 = _g0(rank[row[s]])
        if s in weak:
            g0 = np.maximum(g0, config.UBICADOR_PISO_DEBIL)
        lp += _robust_log(obs[k] - t0 - tt[k], sigma, g0)

    # Estaciones calladas cuando la onda P ya debió llegarles. El original castiga a las 5
    # más cercanas; aquí esas pueden estar a 500 km y un sismo pequeño no les llega. Se
    # castiga entonces a la callada que esté más cerca del epicentro que la segunda estación
    # que sí disparó con fuerza: si dos más lejanas dispararon, esta también debió. No se
    # usa la más lejana porque estaciones a distancias parecidas no siempre disparan (ruido
    # del sitio) y eso castigaba el epicentro correcto.
    tnow = now - ref
    ds = np.sort(D[[row[s] for s in strong]], axis=0)
    reach = ds[min(1, len(ds) - 1)]
    for s in alive:
        if s in picks:
            continue
        rk = rank[row[s]]
        late = tnow - (t0 + malla.tt(s))
        bad = (D[row[s]] < reach) & (late >= config.UBICADOR_NYAD_MARGEN_S)
        lp += np.where(bad, _robust_log(late, sigma, _g0(rk)), 0.0)

    # Zona de Voronoi ampliada: penaliza epicentros más cerca de otra estación que de la
    # primera en disparar (suavemente: con ruido alto la más cercana a veces no dispara).
    # Con piso, porque el primer disparo a veces es ruido (HEL 11 s antes del M4.0 de
    # Istmina del 26-sep): con varios disparos mandan los tiempos, no la primera estación.
    excess = np.maximum(0, D[row[first]] - D.min(axis=0))
    g = config.UBICADOR_PISO_VORONOI
    lp += np.log((1 - g) * np.exp(-excess / config.UBICADOR_C1_KM) + g)

    # Amplitud (ec. 13-16 del artículo): en cada nodo, la magnitud de cada estación frente a
    # la mediana de las que ya completaron su ventana. Una ventana incompleta solo da una
    # cota inferior: castiga solo si ya es demasiado fuerte.
    mterm = None
    if mag is not None and mag.ok and amps and config.UBICADOR_AMPLITUD:
        ms = {s: (_station_magnitude(mag, malla, s, a), c) for s, (a, c) in amps.items()
              if s in picks}
        ms = {s: v for s, v in ms.items() if v[0] is not None}
        full = [m for m, c in ms.values() if c]
        if len(full) >= 2 or (full and len(ms) >= 2):
            mm = np.median(np.stack(full), axis=0)
            sm = config.UBICADOR_SIGMA_M
            for s, (m, c) in ms.items():
                r = m - mm if c else np.maximum(m - mm, 0)
                g0 = _g0(rank[row[s]])
                if s in weak:
                    g0 = np.maximum(g0, config.UBICADOR_PISO_DEBIL)
                lp += _robust_log(r, sm, g0)
            mterm = (ms, mm)

    best = int(np.argmax(lp))
    w = np.exp(lp - lp[best])
    keep = np.flatnonzero(w >= 1e-6)  # el resto no pesa nada (incluye siempre el mejor)
    w = w[keep] / w[keep].sum()
    residuals = {s: float(obs[k, 0] - t0[best] - tt[k][best]) for k, s in enumerate(picks)}
    mres = None
    if mterm:
        ms, mm = mterm
        mres = (mag, mm[keep], {s: (float(m[best] - mm[best]), c) for s, (m, c) in ms.items()})
    return Ubicacion(malla, ref, keep, w, t0[keep], best, residuals, mres)
