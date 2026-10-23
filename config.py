"""Configuración del sistema de alertas de sismos para Medellín."""

MEDELLIN = (6.2476, -75.5658)  # lat, lon

# SeedLink público de EarthScope (rtserve.iris.washington.edu dejó de existir en oct-2026)
SEEDLINK_SERVER = "rtserve.earthscope.org:18000"
# Estación -> (red, ubicación, canal vertical, lat, lon)
STATIONS = {
    # Red CM del SGC
    "HEL": ("CM", "00", "HHZ", 6.1909, -75.529),     # Santa Elena, Medellín (8 km)
    "RUS": ("CM", "00", "HHZ", 5.8927, -73.0828),    # La Rusia, Boyacá
    "OCA": ("CM", "00", "HHZ", 8.2386, -73.3194),    # Ocaña
    "ARGC": ("CM", "00", "HHZ", 9.8577, -74.2458),   # Ariguaní
    "SMAR": ("CM", "00", "HHZ", 11.1638, -74.2245),  # Santa Marta
    "TUM": ("CM", "00", "HHZ", 1.8231, -78.7282),    # Tumaco
    "CRJC": ("CM", "00", "HHZ", 11.0200, -72.8816),  # Cerrejón
    "URI": ("CM", "00", "HHZ", 11.7022, -71.9941),   # Uribia
    "PRV": ("CM", "00", "HHZ", 13.3756, -81.3627),   # Providencia
    # Sur: red global IU y red EC del Instituto Geofísico de Ecuador. PULU y ANTS
    # también están en rtserve, pero están en volcanes y en la prueba del 27-sep
    # dieron 20-29 disparos de ruido en 15 minutos; por eso no se usan.
    "OTAV": ("IU", "00", "BHZ", 0.2376, -78.4508),   # Otavalo, Ecuador
    "PUYO": ("EC", "", "HHZ", -1.4930, -78.0249),    # Puyo, Ecuador
}
LOCAL_STATION = "HEL"  # estación de Medellín
# Estaciones muy cercanas entre sí cuentan como una sola confirmación. Así un sismo
# local o actividad volcánica en Ecuador no produce una alerta por sí solo.
STATION_GROUPS = {"OTAV": "ecuador", "PUYO": "ecuador"}

# Detector STA/LTA
BANDPASS = (2.0, 10.0)  # Hz
STA_S = 1.0
LTA_S = 30.0
THR_ON = 5.0
THR_OFF = 1.5
# Tras apagarse, una estación no vuelve a dispararse durante este tiempo (evita
# disparos repetidos por la coda del mismo sismo)
DEAD_TIME_S = 30
BUFFER_S = 90  # segundos de señal que se guardan por estación
# Si entre dos paquetes de una estación falta más de esto (s), se descarta la señal
# anterior en vez de rellenar el hueco (ver StationTrigger.add)
GAP_RESET_S = 1.0

# Asociación: disparos en varias estaciones dentro de esta ventana = sismo
ASSOC_WINDOW_S = 120
MIN_STATIONS = 2
# Sin HEL hacen falta más confirmaciones: el 28-sep dos disparos sueltos (OTAV y PRV,
# a 1.500 km entre sí) produjeron una falsa alerta con solo 2
MIN_STATIONS_REMOTE = 3
# Solo cuentan para confirmar las estaciones cuya relación STA/LTA máxima llega a
# este valor. En la prueba del 27-sep, los sismos reales dieron 10-30 y el ruido 5-6.
MIN_RATIO = 8.0
# Alertar también cuando solo dispara HEL (baja confianza, puede ser ruido local)
ALERT_LOCAL_ONLY = True
# Relación STA/LTA mínima en HEL para alertar sin confirmación de otras estaciones
LOCAL_ONLY_MIN_RATIO = 8.0

# Qué asociador junta los disparos en detecciones: "ventana" (detector.Associator, todo lo
# que cae en ASSOC_WINDOW_S) o "bayesiano" (asociador.py, ver JAPON.md). Se elige por máquina
# en config_local.py.
ASOCIADOR = "ventana"

# Ubicador y asociador bayesianos (ubicador.py, asociador.py), adaptados del método IPF de
# Japón (Tamaribuchi et al., 2014). Valores del artículo entre paréntesis.
UBICADOR_PASO_GRADOS = 0.2
UBICADOR_PROFUNDIDADES_KM = (5, 15, 30, 50, 75, 100, 125, 150, 175, 200)
# Error típico de un disparo frente al tiempo P teórico (1,5 s). Medido con los sismos
# confirmados del 25-sep al 10-oct: ~4 s (disparos STA/LTA y modelo 1D)
UBICADOR_SIGMA_S = 4.0
# Un disparo es del sismo si cae dentro de ±A·σ de lo esperado (A = 3)
UBICADOR_A = 3
# Qué tan rápido sube el piso de datos anómalos con la distancia, en número de estaciones
# (c2 = 10). Con 3 subía tan rápido que un epicentro junto a una estación ruidosa
# "explicaba" su disparo y descontaba a todas las demás por lejanas
UBICADOR_C2 = 10
# Tope del piso (en el original llega a 1) y peso de la sismicidad previa (1): con ~10
# estaciones los datos pesan poco y sin esto la sismicidad previa decidía sola
UBICADOR_PISO_MAX = 0.2
UBICADOR_PESO_PREVIA = 0.5
# Ancho (km) con que se suaviza la zona de Voronoi de la primera estación (c1 = 10 en una
# red de decenas de km; aquí las estaciones están a cientos de km) y su piso, por si el
# primer disparo fue ruido
UBICADOR_C1_KM = 100
UBICADOR_PISO_VORONOI = 0.05
# Piso de los disparos débiles (STA/LTA < MIN_RATIO): con 0,5 casi no mueven la solución
UBICADOR_PISO_DEBIL = 0.5
# Estaciones calladas: se penalizan si ya pasaron UBICADOR_NYAD_MARGEN_S desde que les debió
# llegar la P (1 s) y están más cerca que la segunda estación que disparó con fuerza
UBICADOR_NYAD_MARGEN_S = 3.0
# Término de amplitud (magnitud.py): magnitud de cada estación frente a la del sismo, con
# σ = 0,7 como en el artículo. Apagado: en el registro de la VM bajó poco las falsas (348 a
# 338) y empeoró la ubicación dentro de la red (mediana 149 a 203 km; ver JAPON.md)
UBICADOR_AMPLITUD = False
UBICADOR_SIGMA_M = 0.7
# Un disparo nuevo se suma a un sismo en curso si lo explica al menos esta fracción de los
# epicentros posibles
ASOCIADOR_P_MIN = 0.2
# Dos sismos en curso se funden si, ubicados juntos, encaja al menos esta fracción de sus
# disparos fuertes (y más que con cada uno por separado)
ASOCIADOR_FUSION_MIN = 0.75
# Un sismo en curso se cierra si no recibe disparos en tanto tiempo, o a esta edad
ASOCIADOR_SILENCIO_S = 120
ASOCIADOR_EDAD_MAX_S = 400

# Magnitud preliminar (magnitud.py, coeficientes en magnitud.json). Ventanas (s desde el
# disparo) en que se mide la amplitud máxima; la de 5 s es la del IPF.
MAGNITUD_VENTANAS_S = (5, 30)
# Banda del desplazamiento con que se mide (la de 2-10 Hz del detector se satura en M5,5) y
# cuántas veces el ruido debe superar para usarlo; si no, se usa la velocidad
MAGNITUD_BANDA_DESP_HZ = (0.2, 5.0)
MAGNITUD_SNR_MIN = 3
# Como la JMA: mediana de las MAGNITUD_ESTACIONES más cercanas al epicentro, sin las que estén
# más de MAGNITUD_MARGEN_KM más lejos que la más cercana (otro sismo o ruido) ni a más de
# MAGNITUD_MAX_KM (el falso M7,3 de Torishima de 2020 salió de estaciones lejanas)
MAGNITUD_ESTACIONES = 5
MAGNITUD_MARGEN_KM = 150
MAGNITUD_MAX_KM = 700

# Búsqueda en catálogos tras una detección
SEARCH_INTERVAL_S = 60
SEARCH_DURATION_S = 30 * 60
# Colombia, Caribe y países vecinos: las estaciones también registran sismos lejanos
REGION = dict(minlat=-6.0, maxlat=20.0, minlon=-86.0, maxlon=-60.0)  # incluye Caribe y vecinos
# Ventana para emparejar un evento de catálogo con la detección
MATCH_BEFORE_S = 300  # el origen puede ser hasta 5 min antes del primer disparo
MATCH_AFTER_S = 15
# Margen (s) al comprobar que las ondas del evento de catálogo pudieron llegar a la
# primera estación entre la onda P y la S (ver server.arrival_misfit)
MATCH_TOLERANCE_S = 15

# Sismicidad de fondo del SGC en el mapa: días que se muestran como máximo y cada cuánto
# se vuelve a consultar el catálogo (la página también se refresca con ese ritmo)
SGC_BACKGROUND_MAX_DAYS = 30
SGC_BACKGROUND_REFRESH_S = 30 * 60

# Avisos de GDACS (sismos grandes del mundo con nivel de alerta de impacto): cada cuánto se
# consulta, cuántos días se muestran y qué avisa la página. Se notifica toda alerta de esos
# niveles en cualquier parte del mundo, y cualquier sismo de GDACS dentro de REGION.
GDACS_REFRESH_S = 10 * 60
GDACS_DAYS = 30
GDACS_NOTIFY_LEVELS = ("Orange", "Red")

# Consultar la API del SGC desde el servidor (confirmación de detecciones y sismicidad de
# fondo). El SGC bloquea las IPs de centros de datos (Azure: 403): en esas máquinas conviene
# False en config_local.py; el mapa la consulta entonces desde el navegador.
USE_SGC = True

# Feed de archive.sgc.gov.co: trae eventos preliminares, pero bloquea clientes
# que no son navegador. Mantener apagado hasta tener autorización del SGC.
USE_SGC_ARCHIVE_FEED = False

# Servidor web local
HTTP_HOST = "127.0.0.1"
HTTP_PORT = 8765
# Páginas que pueden leer /sismos-detectados.geojson desde el navegador (CORS): el visor
# sismos-3d-colombia en Vercel (producción y vistas previas), GitHub Pages y pruebas locales.
VISOR_ORIGINS = (r"^https://sismos-3d-colombia(-[a-z0-9-]+)?\.vercel\.app$"
                 r"|^https://jduquetr\.github\.io$"
                 r"|^http://(localhost|127\.0\.0\.1)(:\d+)?$")

# Ajustes propios de cada máquina (p. ej. USE_SGC = False en Azure, otro puerto): van en
# config_local.py, que git ignora. Así la actualización diaria (git pull) nunca choca con
# ellos y cada máquina conserva los suyos.
try:
    from config_local import *  # noqa: F401,F403
except ImportError:
    pass
