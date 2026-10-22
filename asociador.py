"""Asociador que separa sismos simultáneos y ruido (método IPF de Japón).

El asociador de detector.py junta todo disparo que cae dentro de 120 s del primero. Así,
dos disparos sueltos lejanos (OTAV y PRV el 28-sep) o un disparo viejo de otra estación
terminan en una misma detección. Aquí, como en Tamaribuchi et al. (2014):

1. El primer disparo abre un sismo y se ubica (ubicador.ubicar).
2. Cada disparo nuevo se suma a los sismos en curso que lo explican (Ubicacion.explica):
   su hora encaja con la onda P desde los epicentros posibles. Si ninguno lo explica,
   abre un sismo nuevo, que es otro sismo o ruido.
3. Si más de la mitad de los disparos de un sismo los explica otro, eran el mismo y se
   funden (pasa cuando el primer disparo de un sismo fue ruido). Como con pocas estaciones
   cada mitad se ubica mal, también se funden si ubicados juntos encajan (_same_quake).
4. Un sismo se declara detección con las mismas reglas de siempre (MIN_STATIONS,
   MIN_STATIONS_REMOTE, HEL sola), pero contando solo sus propios disparos.
5. Cada detección lleva una magnitud preliminar con la velocidad máxima de sus estaciones
   más cercanas (magnitud.py), si se le pasan las amplitudes (amps).

Tiene la misma interfaz que detector.Associator, así que el servidor puede usar uno u otro.
"""
import threading
from itertools import count

from obspy import UTCDateTime

import config
from detector import Associator, n_groups
from magnitud import Magnitud
from ubicador import Malla, ubicar


class _Sismo:
    _ids = count(1)

    def __init__(self, station, onset, ratio):
        self.n = next(self._ids)
        self.picks = {station: {"onset": onset, "ratio": float(ratio)}}
        self.first = onset
        self.last = onset
        self.loc = None
        self.det = None

    def onsets(self):
        return {s: p["onset"] for s, p in self.picks.items()}


class BayesAssociator:
    def __init__(self, on_detection, on_update, malla=None, alive=None, clock=None,
                 amps=None, magnitud=None):
        self.on_detection = on_detection
        self.on_update = on_update
        self.malla = malla or Malla()
        self.alive = alive or (lambda: list(self.malla.stations))  # estaciones con datos
        self.clock = clock or UTCDateTime  # en pruebas: la hora simulada
        # amps(estación) -> (hora del disparo, {ventana: cuentas}) del último disparo
        self.amps = amps
        self.magnitud = magnitud or Magnitud()
        self.lock = threading.Lock()
        self.open = []  # sismos en curso

    def trigger(self, station, onset, ratio):
        with self.lock:
            self._expire(onset)
            touched = []
            for ev in self.open:
                if station in ev.picks:
                    continue  # la misma estación otra vez (coda): no es un dato nuevo
                if ev.loc.explica(station, onset) >= config.ASOCIADOR_P_MIN:
                    ev.picks[station] = {"onset": onset, "ratio": float(ratio)}
                    ev.last = max(ev.last, onset)
                    touched.append(ev)
            if not touched:
                ev = _Sismo(station, onset, ratio)
                self.open.append(ev)
                touched.append(ev)
            for ev in touched:
                self._locate(ev, onset)
            for ev in dict.fromkeys(touched + self._merge(onset, touched)):
                if ev in self.open:
                    self._decide(ev)

    def peak(self, station, ratio):
        with self.lock:
            for ev in self.open:
                p = ev.picks.get(station)
                if p and ratio > p["ratio"] + 0.5:
                    p["ratio"] = float(ratio)
                    self._decide(ev, quiet=True)

    def refresh(self):
        """Vuelve a calcular la magnitud de las detecciones en curso (cada pocos segundos).

        La velocidad máxima sigue subiendo después del disparo, cuando ya no llegan disparos
        nuevos que obliguen a recalcular; se avisa si la magnitud cambió.
        """
        with self.lock:
            for ev in self.open:
                if ev.det is None:
                    continue
                mag = self._magnitude(ev)
                old = (ev.det.get("magnitud") or {}).get("valor")
                if mag and mag["valor"] != old:
                    self._decide(ev)

    def _locate(self, ev, now):
        """Ubica el sismo y saca los disparos que no encajan, si ya hay con qué juzgarlos.

        Un disparo de ruido que llegó primero abre el sismo y los verdaderos se le suman
        (con un solo disparo cualquier cosa encaja). Cuando al menos 3 disparos fuertes
        encajan, los que no son de otra cosa: se quitan y se vuelve a ubicar.
        """
        ev.loc = self._ubicar(ev.picks, now)
        strong = {s for s, p in ev.picks.items() if p["ratio"] >= config.MIN_RATIO}
        fit = set(ev.loc.fits())
        if len(fit & strong) >= 3 and set(ev.picks) - fit:
            ev.picks = {s: p for s, p in ev.picks.items() if s in fit}
            ev.first = min(p["onset"] for p in ev.picks.values())
            ev.loc = self._ubicar(ev.picks, now)

    def _ubicar(self, picks, now):
        weak = {s for s, p in picks.items() if p["ratio"] < config.MIN_RATIO}
        return ubicar(self.malla, {s: p["onset"] for s, p in picks.items()}, now, self.alive(), weak)

    def _same_quake(self, a, b, now):
        """¿Son a y b el mismo sismo? Devuelve la ubicación conjunta si lo son.

        Primero la regla del artículo: más de la mitad de los disparos de b los explica a.
        Si no, se ubican juntos: un sismo partido en dos (porque su primer disparo fue ruido)
        se ubica mal por partes y ninguna explica a la otra, pero junto encaja. Con 4 o más
        disparos fuertes la ubicación conjunta ya no se acomoda a cualquier cosa.
        """
        shared = sum(1 for s, p in b.picks.items()
                     if s in a.picks or a.loc.explica(s, p["onset"]) >= config.ASOCIADOR_P_MIN)
        union = dict(b.picks, **a.picks)  # si una estación está en ambos, vale el de a
        if shared * 2 > len(b.picks):
            return self._ubicar(union, now)
        strong = {s for s, p in union.items() if p["ratio"] >= config.MIN_RATIO}
        if len(strong) < 4:
            return None
        loc = self._ubicar(union, now)
        n_fit = len(loc.fits(strong))
        alone = max(len(a.loc.fits(strong)), len(b.loc.fits(strong)))
        if n_fit >= config.ASOCIADOR_FUSION_MIN * len(strong) and n_fit > alone:
            return loc
        return None

    def _expire(self, now):
        self.open = [ev for ev in self.open
                     if now - ev.last <= config.ASOCIADOR_SILENCIO_S
                     and now - ev.first <= config.ASOCIADOR_EDAD_MAX_S]

    def _merge(self, now, dirty):
        """Funde sismos que son el mismo (_same_quake). Devuelve los que cambiaron.

        Solo se prueban pares donde al menos uno acaba de cambiar (dirty): los demás ya se
        probaron antes y cada prueba puede costar una ubicación.
        """
        changed = []
        dirty = set(dirty)
        merged = True
        while merged:
            merged = False
            for a in self.open:
                for b in self.open:
                    if a is b or len(b.picks) > len(a.picks) or not {a, b} & dirty:
                        continue
                    if self._same_quake(a, b, now):
                        for s, p in b.picks.items():
                            a.picks.setdefault(s, p)
                        a.first, a.last = min(a.first, b.first), max(a.last, b.last)
                        a.det = a.det or b.det
                        self._locate(a, now)  # con la depuración de disparos ajenos
                        self.open.remove(b)
                        changed.append(a)
                        dirty.add(a)
                        merged = True
                        break
                if merged:
                    break
        return changed

    def _magnitude(self, ev):
        if not self.amps or not self.magnitud.ok:
            return None
        for s, p in ev.picks.items():
            a = self.amps(s)
            if a and a[0] == p["onset"]:
                p["amps"] = dict(a[1])  # copia: el próximo disparo de la estación la reemplaza
        amps = {s: (p["onset"], p["amps"]) for s, p in ev.picks.items() if p.get("amps")}
        return self.magnitud.estimar(amps, ev.loc, self.clock())

    def _decide(self, ev, quiet=False):
        """Declara la detección cuando sus disparos propios cumplen las reglas de siempre."""
        strong = [s for s, p in ev.picks.items() if p["ratio"] >= config.MIN_RATIO]
        local = ev.picks.get(config.LOCAL_STATION)
        local_strong = (config.ALERT_LOCAL_ONLY and local is not None
                        and local["ratio"] >= config.LOCAL_ONLY_MIN_RATIO)
        needed = (config.MIN_STATIONS if config.LOCAL_STATION in strong
                  else config.MIN_STATIONS_REMOTE)
        if ev.det is None and not (n_groups(strong) >= needed or local_strong):
            return
        anchors = strong or [config.LOCAL_STATION]
        first = min(ev.picks[s]["onset"] for s in anchors if s in ev.picks)
        new = ev.det is None
        if new:
            ev.det = {"id": f"DET{first.strftime('%Y%m%d%H%M%S')}", "first_onset": first,
                      "detected_at": self.clock()}
        det = ev.det
        old_level = det.get("level")
        det["stations"] = {s: {"onset": str(p["onset"]), "ratio": round(p["ratio"], 1)}
                           for s, p in sorted(ev.picks.items(), key=lambda x: x[1]["onset"])}
        det["ubicacion"] = ev.loc.to_dict()
        Associator._set_level(det)
        mag = self._magnitude(ev)
        if mag:
            det["magnitud"] = mag
            det["message"] += f". Magnitud preliminar ≈ {mag['valor']}"
        if new:
            self.on_detection(det)
        elif not quiet or det["level"] != old_level:
            self.on_update(det)
