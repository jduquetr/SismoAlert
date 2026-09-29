# Alertas de sismos · Medellín (prototipo)

Detecta sismos en tiempo real con estaciones del SGC (red CM) que retransmite el SeedLink
público de IRIS. Busca cada detección en los catálogos del SGC, USGS y EMSC, y avisa con
notificaciones del navegador.

## Flujo

1. **SeedLink** (`rtserve.iris.washington.edu:18000`): 9 estaciones CM del SGC más IU.OTAV
   y EC.PUYO en Ecuador, con unos 10–30 s de retraso. HEL (Santa Elena) está a 8 km de
   Medellín. Las dos de Ecuador cuentan como una sola confirmación. PULU y ANTS no se usan:
   son estaciones volcánicas y dan demasiado ruido.
2. **Detector STA/LTA** por estación: banda 2–10 Hz, STA 1 s, LTA 30 s, umbral 5.
3. **Asociación**, con tres niveles de alerta:
   - **alta**: 2 o más estaciones con STA/LTA ≥ 8 y HEL entre ellas (probablemente sentido en Medellín).
   - **media**: 2 o más estaciones con STA/LTA ≥ 8, sin HEL.
   - **baja**: solo HEL, con STA/LTA ≥ 8 (puede ser ruido local).
4. **Búsqueda en catálogos**: cada 60 s durante 30 min consulta el SGC (API biweekly) y el
   USGS. EMSC llega por **websocket** (`emsc.py`), así que sus eventos se asocian apenas se
   publican. También se consulta cuántas personas reportaron en EMSC haberlo sentido. Si EMSC
   publica un sismo relevante que las estaciones no detectaron, se alerta igual con el nivel
   **catálogo**. Cada evento encontrado se clasifica como crítica, informativa o silenciosa
   según la magnitud y la distancia hipocentral a Medellín.
5. **Página local** (`http://127.0.0.1:8765`): muestra el estado de las estaciones, las
   detecciones y los datos de catálogo, y lanza notificaciones con sonido.
6. **Mapa** (Leaflet + OpenStreetMap):
   - Las estaciones aparecen como triángulos: verde si reciben datos, rojo si están disparadas,
     gris si no llegan datos.
   - Medellín tiene círculos de distancia de 100, 200, 300 y 500 km.
   - Cada sismo detectado se dibuja en la ubicación revisada por el SGC (círculo relleno). Si el
     SGC aún no la publica, se usa la preliminar o la de USGS/EMSC (círculo punteado).
   - Al pulsar una detección, el mapa se centra en ella y resalta las estaciones que dispararon.

IRIS ya no tiene servicio de eventos (fue retirado), así que se usa EMSC en su lugar.

**Emparejamiento con catálogos.** Un evento de catálogo solo se asocia a una detección si
sus ondas pudieron llegar a la primera estación fuerte entre la onda P y la S, con 15 s de
margen. Para eso se usa el modelo de `traveltime.py`: P por la corteza (6,1 km/s) o por el
manto (Pn, 8,0 km/s + 5 s); S por la corteza (3,5 km/s) o Sn (4,6 km/s + 9 s). La página
usa el mismo modelo en la animación.

## Datos guardados (`datos/`)

Todo se guarda en un **único archivo**, `datos/sismos-detectados.geojson`, con un registro
(Feature) por detección real. Se reescribe completo cada vez que hay una detección nueva o
información nueva de una existente.

- `geometry`: la ubicación del catálogo (la revisada del SGC si existe) como
  `[lon, lat, prof]`. Queda en `null` mientras ningún catálogo la publique.
- `properties`: los campos que lee sismos-3d-colombia (`id`, `time`, `mag`, `depth`,
  `place`), más:
  - `resumen`: estaciones en orden con su diferencia con la P esperada, distancia a Medellín,
    llegada de P y S a Medellín y ventaja de la alerta sobre la onda S;
  - `deteccion`: el detalle completo (estaciones, catálogos, reportes "sentido").

El archivo se importa directamente en sismos-3d-colombia, que salta los registros sin
ubicación. Las detecciones de prueba no se guardan.

Al arrancar, el servidor recarga las últimas 30 detecciones guardadas.

## Uso (Windows, Python 3.11+)

```
git clone https://github.com/jduquetr/SismoAlert.git C:\sismos-alerta
cd C:\sismos-alerta
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\iniciar.bat
```

En la página, pulsa **Activar notificaciones y sonido** y acepta el permiso del navegador.
El botón **Probar con el sismo de Istmina** simula una detección del M4.3 del 27-sep-2026
y busca ese sismo real en los tres catálogos.

## Copia estática para compartir (`docs/`)

`docs/index.html` es una copia de la página local con los datos del servidor en el momento en
que se generó: estaciones, detecciones y registro. Funciona sin servidor y no se actualiza sola.
Se publica en https://sismo-alert-blue.vercel.app: Vercel despliega cada push a `main` y solo
recibe `docs/` (ver `.vercelignore`).

Para publicar datos nuevos, con el servidor en marcha:

```
.\.venv\Scripts\python.exe copia_estatica.py
git add docs/index.html
git commit -m "Actualizar copia estática"
git push
```

El mapa tiene un selector de mapa base, arriba a la derecha: calles, topográfico, satélite,
relieve sombreado, claro, oscuro y contornos sin conexión. Recuerda la última elección.

## Calibración

`python replay.py <hora UTC> [min_antes] [min_despues]` corre el detector sobre datos
archivados del SGC como si llegaran en vivo. Así se ajustan los umbrales de `config.py`.
Con 2026-09-27T21:57:52 10 5, detecta el M4.8 de República Dominicana y el M4.3 de
Istmina sin falsas alarmas.

## Pendiente

- Base de sismos sentidos en Medellín para reemplazar la función `priority()` provisional.
- Feed `archive.sgc.gov.co`, con eventos preliminares: está en `sources.sgc_archive`, apagado
  con `USE_SGC_ARCHIVE_FEED`. Hay que pedir autorización al SGC (datos@sgc.gov.co).
- Llevarlo a la Raspberry Pi y enviar al celular (ntfy/Telegram).
