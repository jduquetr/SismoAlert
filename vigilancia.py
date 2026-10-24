"""Aviso cuando una estación deja de mandar datos y cuando vuelve.

Sin datos de una estación el sistema sigue andando, pero con menos ojos: si cae HEL,
Medellín se queda sin PLUM ni Pd y sin la confirmación local. Por eso se avisa en vez de
dejarlo solo como un número en la lista de estaciones.
"""
import time

import config


class Vigilancia:
    def __init__(self, caida_s=None, clock=time.time):
        self.caida_s = caida_s or config.ESTACION_CAIDA_S
        self.clock = clock
        self.inicio = clock()
        self.caidas = set()

    def revisar(self, ultimos):
        """ultimos: {estación: hora (reloj local) del último paquete o None}.

        Devuelve [(estación, "caida" | "vuelve", segundos sin datos)] con los cambios. Al
        arrancar se espera caida_s antes de dar por caída una estación que nunca mandó nada.
        """
        now = self.clock()
        cambios = []
        for sta, t in ultimos.items():
            edad = now - (t if t else self.inicio)
            if edad > self.caida_s and sta not in self.caidas:
                self.caidas.add(sta)
                cambios.append((sta, "caida", round(edad)))
            elif edad <= self.caida_s and sta in self.caidas and t:
                self.caidas.discard(sta)
                cambios.append((sta, "vuelve", round(edad)))
        return cambios
