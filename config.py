"""Configuración del sistema de alertas de sismos para Medellín."""

MEDELLIN = (6.2476, -75.5658)  # lat, lon

# SeedLink público de IRIS/EarthScope
SEEDLINK_SERVER = "rtserve.iris.washington.edu:18000"
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
