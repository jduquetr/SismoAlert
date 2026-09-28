"""Modelo regional sencillo de tiempos de viaje de las ondas P y S.

La primera onda en llegar es la más rápida entre la que viaja por la corteza (Pg/Sg) y
la que baja al techo del manto y viaja por él (Pn/Sn), que gana a más de ~150-200 km.
Con el M4.3 de Istmina del 27-sep predice HEL, RUS y OCA con 1-3 s de error, frente a
4-17 s con una velocidad constante de 6 km/s. La página usa las mismas constantes.
"""
import math

VP_CRUST, VP_MANTLE, TAU_P = 6.1, 8.0, 5.0  # km/s, km/s, s (retraso por bajar y subir)
VS_CRUST, VS_MANTLE, TAU_S = 3.5, 4.6, 9.0


def p_time(dist_km, depth_km):
    return min(math.hypot(dist_km, depth_km) / VP_CRUST, dist_km / VP_MANTLE + TAU_P)


def s_time(dist_km, depth_km):
    return min(math.hypot(dist_km, depth_km) / VS_CRUST, dist_km / VS_MANTLE + TAU_S)
