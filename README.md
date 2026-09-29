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

## Uso en macOS (computador que vigila)

Requiere Python 3.11 o más reciente. El `python3` que trae macOS suele ser más antiguo:
instálalo desde python.org o con `brew install python@3.12`.

```
git clone https://github.com/jduquetr/SismoAlert.git ~/sismos-alerta
cd ~/sismos-alerta
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
chmod +x iniciar.sh
./iniciar.sh --abrir          # prueba a mano; Ctrl+C para detenerlo
```

**Dejarlo corriendo solo.** `sh mac/instalar_servicio.sh` lo registra en launchd: arranca al
iniciar sesión, se reinicia si se cae y escribe en `server.log`. Para quitarlo, usa
`sh mac/instalar_servicio.sh --quitar`. El servicio corre dentro de la sesión del usuario, así
que conviene activar el inicio de sesión automático (Ajustes del Sistema → Usuarios y grupos).

**Que no se duerma.** Con el Mac conectado a la corriente:

```
sudo pmset -c sleep 0 disksleep 0
```

En un MacBook, deja la tapa abierta: al cerrarla se suspende salvo que tenga una pantalla
externa. La pantalla sí puede apagarse; eso no detiene el servidor.

**Comprobar que funciona.**
- Abre `http://127.0.0.1:8765`: las estaciones deben estar en verde.
- Revisa el registro con `tail -f server.log`.
- Pide el estado de las estaciones con
  `curl -s http://127.0.0.1:8765/state | python3 -m json.tool | grep -E '"station"|last_packet'`.

**Verlo desde afuera (Tailscale).**
1. Instala Tailscale en el Mac y en tu celular o portátil, con la misma cuenta.
2. En login.tailscale.com/admin/dns, activa MagicDNS y HTTPS Certificates.
3. En el Mac, ejecuta `tailscale serve --bg 8765`. Con la app de la Mac App Store, el comando
   es `/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --bg 8765`.
4. Abre desde tus dispositivos la dirección `https://<nombre-del-mac>.<tailnet>.ts.net` que
   muestra el comando.

El servidor sigue escuchando solo en `127.0.0.1`: nadie fuera de tu red de Tailscale puede
verlo, y el HTTPS permite que funcionen las notificaciones del navegador.

**Publicar en Vercel automáticamente.** El Mac vigilante puede mantener al día
https://sismo-alert-blue.vercel.app y el respaldo que usa el visor. Primero, una sola vez:

```
brew install gh
gh auth login            # entrar con la cuenta de GitHub dueña de SismoAlert
gh auth setup-git        # git push usa esa sesión, también desde launchd
git config user.name "Tu nombre"
git config user.email tu@correo
./publicar.sh --forzar   # prueba: debe terminar con "publicado en Vercel" en publicar.log
sh mac/instalar_publicacion.sh
```

`publicar.sh` corre cada hora (`INTERVALO` en `mac/instalar_publicacion.sh`). Solo hace commit y push de `docs/` si cambió el registro
de sismos, o una vez al día para refrescar el estado de las estaciones. Deja lo que hace en
`publicar.log`. Para quitarlo: `sh mac/instalar_publicacion.sh --quitar`. Desde que el Mac
publica, no conviene publicar `docs/` desde otro computador: sus cambios chocarían.

Estos mismos pasos sirven en la Raspberry Pi (Linux). Solo cambia el arranque automático:
se hace con un servicio de systemd en lugar de launchd.

## Servidor en la nube (Linux) y avisos por Telegram

El mismo servidor corre en una máquina virtual Linux (probado en Azure, Ubuntu 24.04,
Standard_B2ats_v2 con 1 GB de RAM y 1 GB de swap), así no depende de un computador encendido.

```
git clone https://github.com/jduquetr/SismoAlert.git ~/sismos-alerta
cd ~/sismos-alerta
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
sh linux/instalar_servicio.sh
```

`linux/instalar_servicio.sh` lo registra en systemd (arranca con la máquina y se reinicia si
se cae) y programa `linux/actualizar.sh` cada 5 minutos: si hay cambios en GitHub los trae y
reinicia el servicio. Registro: `journalctl -u sismoalert -f`.

**Telegram.** Crea un bot con @BotFather, escríbele algo y toma tu `chat_id` de
`https://api.telegram.org/bot<TOKEN>/getUpdates` (para un grupo o canal, agrega el bot y usa
el id que empieza por `-100`). Luego, en el servidor, crea `/etc/sismoalert.env` con permisos
600 y reinicia el servicio (`sudo systemctl restart sismoalert`):

```
TELEGRAM_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789
SISMOALERT_URL=https://sismo-alert-blue.vercel.app
```

`telegram.py` avisa de cada detección (con sonido si es alta o media), de la primera
confirmación en un catálogo y de cada subida de prioridad, de las estaciones que dejan de
enviar datos más de 10 minutos (`TELEGRAM_STALE_S`) y manda un resumen diario a las 7:00 de
Colombia (`TELEGRAM_DAILY_HOUR`). Sin esas variables no envía nada. El botón de prueba de la
página también llega a Telegram, marcado como PRUEBA.

**Catálogo del SGC desde la nube.** `api.sgc.gov.co` responde 403 a las IP de Azure: desde
ahí las detecciones se confirman con USGS y EMSC, y el mapa queda sin la sismicidad de fondo
del SGC.

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

El mapa tiene un selector de mapa base, plegado en un ícono arriba a la derecha: calles,
topográfico, satélite, relieve sombreado, claro, oscuro y contornos sin conexión. La página
tiene además un control de volumen para la alerta. Ambos se recuerdan en cada navegador.

`copia_estatica.py` también publica `docs/sismos-detectados.geojson`, con CORS abierto. El
botón "Sismos sentidos (SPAlert)" del visor sismos-3d-colombia lo usa como respaldo cuando no
alcanza el servidor en vivo.

## Sismicidad de fondo del SGC en el mapa

El servidor consulta cada 30 minutos el catálogo del SGC de los últimos 30 días y lo entrega
en `/sgc-sismos?dias=7|14|30`. Los parámetros están en `config.py`:
`SGC_BACKGROUND_MAX_DAYS` y `SGC_BACKGROUND_REFRESH_S`.

El mapa lo dibuja como puntos bajo las detecciones propias, con un control abajo a la
izquierda:
- el periodo, de 7, 14 o 30 días;
- la visibilidad: de gris casi transparente, para que no robe protagonismo, a color por
  profundidad y opaco.

La página se refresca con el mismo ritmo, y la copia estática incluye esos datos.

## Visor de sismos (evento especial SPAlert)

El servidor entrega el registro en `http://127.0.0.1:8765/sismos-detectados.geojson`, con
CORS solo para las páginas del visor (`config.VISOR_ORIGINS`). En el visor, el botón "Sismos
sentidos (SPAlert)" lo carga como evento especial. El campo de dirección acepta
`http://127.0.0.1:8765` en el mismo equipo o la dirección de Tailscale (`https://….ts.net`)
del computador que vigila. Si no responde, carga la copia publicada en Vercel y avisa de qué
fecha es.

## Calibración

`python replay.py <hora UTC> [min_antes] [min_despues]` corre el detector sobre datos
archivados del SGC como si llegaran en vivo. Así se ajustan los umbrales de `config.py`.
Con 2026-09-27T21:57:52 10 5, detecta el M4.8 de República Dominicana y el M4.3 de
Istmina sin falsas alarmas.

## Pendiente

- Base de sismos sentidos en Medellín para reemplazar la función `priority()` provisional.
- Feed `archive.sgc.gov.co`, con eventos preliminares: está en `sources.sgc_archive`, apagado
  con `USE_SGC_ARCHIVE_FEED`. Hay que pedir autorización al SGC (datos@sgc.gov.co).
- Llevarlo a la Raspberry Pi.
