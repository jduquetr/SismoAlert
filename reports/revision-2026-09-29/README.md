# Revisión de SismoAlert — 29 de septiembre de 2026

Rama de trabajo: `codex-revision`, creada desde `origin/azure-telegram` (`72d978b`).
No se desplegó ni se modificó la máquina de Azure. Todos los tiempos de este informe son UTC.

## Cambios de comportamiento

### Telegram, hilos y catálogos

- `server.py` y `Associator` comparten un `RLock` para serializar las mutaciones de detecciones, asociación y callbacks de EMSC. Las consultas HTTP y las esperas ocurren fuera del bloqueo. `Hub` guarda y entrega copias profundas, evitando que el hilo SSE o `/state` recorra diccionarios que otro hilo modifica.
- `on_detection` registra la búsqueda **antes** de arrancar el hilo y rechaza el mismo ID por segunda vez. El aviso de EMSC sin estaciones contiene desde el principio el evento confirmado: no envía primero un «posible sismo» y después una confirmación. Los `create` repetidos y las revisiones se asocian al ID conocido, incluso después de acabar la búsqueda. Un `update` que hace relevante un evento por primera vez también avisa. No se anuncian como nuevos eventos de más de 30 minutos reenviados al reconectar.
- Si el aviso de EMSC precede a las ondas, la detección de estaciones enriquece la misma fila. Las coincidencias por tiempo eligen una sola detección. Las pruebas y los descartes no capturan eventos reales del websocket.
- `attach` compara el evento completo: una revisión de profundidad o ubicación puede cambiar distancia y prioridad aunque no cambie magnitud/estado. Conserva los testimonios del mismo evento.
- EMSC REST siempre consulta la ventana completa; un caché websocket parcial ya no oculta otros eventos de la ventana.
- Un descarte no vuelve a producir avisos de subida de nivel ni de confirmación. La heurística de simultaneidad no invalida una detección ya confirmada por catálogo. `search_catalogs` siempre cierra su estado y retira `active`, incluso ante excepciones; distingue errores por fuente de consultas exitosas sin coincidencias. Ya no interpreta una indisponibilidad como probable falsa alarma. La página usa esos mismos estados y muestra explícitamente cuando SGC está desactivado.
- Al reiniciar, se restauran los máximos de notificación conocidos y se retoman búsquedas pendientes, respetando su plazo original. Esto evita reanunciar el historial; no es un recibo de entrega de Telegram.
- `telegram.py` serializa las transiciones y limita su historial a 2.048 detecciones. Solo consume una transición si la cola la acepta. El worker valida la respuesta, cierra conexiones, completa cada elemento de cola, respeta `retry_after` en HTTP 429 y no reintenta errores permanentes 4xx. Los logs no incluyen URLs que puedan contener el token. Los mensajes con más de diez minutos en cola vencen para no reproducir alarmas antiguas al recuperarse la conexión. El arranque es idempotente y todos los mensajes de pruebas llevan la marca PRUEBA.
- La salud comprueba la edad de la **muestra**, además de la llegada de paquetes: recibir datos atrasados no equivale a estar al día. Las transiciones que no entran en la cola se intentan en el siguiente chequeo. El resumen diario usa el registro completo (`store.count_recent`), no solo las últimas 30 filas de la pantalla.
- En `Associator.peak` se comprueba el inicio al que pertenece cada pico. Antes, una estación de un sismo anterior podía desviar al evento viejo el pico del disparo nuevo pendiente. Se reemplaza la entrada pendiente al llegar un disparo nuevo de la misma estación y se evita asociar tiempos negativos.

**Límites:** la cola de Telegram sigue en memoria. Un corte de proceso puede perder mensajes pendientes y un timeout después de que Telegram acepte un mensaje puede causar repetición al reintentarlo: `sendMessage` no ofrece aquí una clave de idempotencia. Se registran fallos, pero no se promete entrega exactamente una vez. El historial de EMSC usado para deduplicar sigue acotado a las detecciones cargadas/activas. La confirmación por tiempos conserva la tolerancia existente, que permite una estación compatible; no equivale a una localización sismológica independiente.

### Actualización y systemd

`linux/actualizar.sh` ahora:

1. Corre como usuario sin privilegios y toma un `flock`; nunca actualiza desde otra rama ni otro remoto.
2. Solo trae `origin/azure-telegram`, con fast-forward. Un `fetch` fallido, historia divergente o cambios locales da error visible. Ya no descarta cambios de `docs/`.
3. Comprueba sintaxis Python y permiso de reinicio antes de mover `HEAD`. El cuerpo del script se analiza como función antes de que Git lo reemplace.
4. **Detiene la actualización si cambia `requirements.txt`.** Evita un `pip` parcialmente aplicado sobre el entorno vivo. La preparación de dependencias se hace manualmente en un entorno aparte; el servicio continúa usando la versión anterior mientras tanto.
5. Comprueba systemd y `/state` tras reiniciar. Si falla, intenta volver con `git reset --keep` al commit anterior y reiniciar; reporta fallo aunque el rollback funcione. Si aparecieron cambios incompatibles, aborta el rollback y exige intervención. Un cambio solo en `docs/` no reinicia.

`linux/instalar_servicio.sh` rechaza root, ramas distintas de `azure-telegram` y metacaracteres en usuario/ruta; protege `/etc/sismoalert.env` como root:root 0600; usa archivos temporales privados e instala unidades propiedad de root. Configura un permiso sudo **solo** para `/usr/bin/systemctl restart sismoalert.service`, validado con `visudo`, sin conceder ejecución de scripts como root. Cron utiliza rutas y PATH explícitos. El servicio ejecuta Python directamente con `NoNewPrivileges`, `PrivateTmp`, sistema/home de solo lectura y escritura únicamente en `datos/`.

**Primera adopción en Azure, después de aprobar y fusionar el PR:** ejecutar una vez `sh linux/instalar_servicio.sh` desde la rama de producción para instalar la nueva unidad y el permiso de reinicio. Un `git pull` por sí solo no actualiza `/etc/systemd/system`. No se ejecutó este paso durante la revisión. Si el repo tiene modificaciones de `docs/`, resolverlas explícitamente antes de habilitar la actualización.

**Dependencias futuras:** detener temporalmente cron de SismoAlert, preparar en otro directorio/checkout un venv con los nuevos requisitos y correr pruebas; durante una ventana de mantenimiento detener el servicio, avanzar la rama con `--ff-only`, reemplazar el entorno y reiniciar. Conservar commit y entorno anteriores para rollback y reactivar cron al comprobar `/state`. No hacer `pip install` sobre un venv que el servidor utiliza en ese momento.

## Calibración mediante replay

### Método y reproducibilidad

Se descargaron las 11 estaciones configuradas para diez ventanas independientes (153 minutos de señal en total). Cada ventana tiene datos de las 11 estaciones y más del 99 % del intervalo por estación; no es una medición de disponibilidad continua de la red. El conjunto de ajuste contiene cuatro eventos objetivo y dos ventanas de fondo. Después de seleccionar el umbral se comprobaron tres eventos adicionales y una hora de fondo.

`replay.py` conserva huecos de señal: elimina el `merge(..., fill_value="interpolate")` global que antes los inventaba. Reproduce paquetes de 2 s por orden cronológico y registra la hora simulada de llegada que produjo la detección. Guarda parámetros, cobertura por estación, proveedor, solicitud exacta y SHA-256 del MiniSEED. Las descargas quedan en `datos/replay/`, fuera de Git. Los JSON de este directorio son resultados reales de la ejecución; no son fixtures sintéticos.

```sh
# Una ventana con el ajuste propuesto:
.venv/bin/python replay.py 2026-09-27T21:57:51 10 5 --output /tmp/istmina.json
# Perfil anterior, manteniendo los arreglos del detector:
.venv/bin/python replay.py 2026-09-27T21:57:51 10 5 --offline \
  --set MIN_RATIO=8 --set LOCAL_ONLY_MIN_RATIO=8 --output /tmp/istmina-base.json
# Matriz completa (38 ejecuciones); omitir --offline para descargar la caché faltante:
.venv/bin/python tools/calibrate.py --offline
# Coincidencias usando los catálogos congelados en este informe:
.venv/bin/python tools/summarize_replays.py
```

Entorno: Python 3.14.7/macOS ARM64; versiones exactas en `environment.txt`. Para repetir los resultados sin cambios de librerías, instalar ese archivo en un venv compatible. Los perfiles comparan **parámetros** sobre el detector corregido; «base» no significa ejecutar sin los arreglos de asociación. Los catálogos congelados sirven de referencia retrospectiva, sin simular sus retrasos de publicación.

### Resultado y selección

Se cambian `MIN_RATIO` y `LOCAL_ONLY_MIN_RATIO` de **8 a 10**. Permanecen `THR_ON=5`, `THR_OFF=1.5`, STA/LTA=1/30 s, ventana=120 s y 2 grupos con HEL/3 sin HEL.

| Evento objetivo (origen UTC; magnitud SGC) | Fase del experimento | Primera alerta con 8 | Primera alerta con 10 | Resultado final con 10 |
|---|---|---:|---:|---|
| Istmina M4,0 · 25-sep 00:57:05 | Ajuste | +36 s | +36 s | Alta, coincide |
| Chaparral M4,5 · 26-sep 06:38:16 | Ajuste | +44 s | +44 s | Alta, coincide |
| Istmina M4,3 · 27-sep 21:57:51 | Ajuste | +36 s | +36 s | Alta, coincide |
| Los Santos M4,1, 145 km prof. · 28-sep 14:42:32 | Ajuste | +42 s | +42 s | Alta, coincide |
| Istmina M3,6 · 24-sep 07:39:04 | Validación | +36 s | +36 s | Alta, coincide |
| Istmina M3,9 · 27-sep 03:15:38 | Validación | +38 s | +38 s | Alta, coincide |
| Chaparral M4,2 · 28-sep 08:39:54 | Validación | +44 s | +44 s | Alta, coincide |

Estos segundos se cuentan desde el origen de referencia hasta el paquete que emite la **primera** alerta, que puede ser de nivel bajo y subir después. No incluyen el retraso de SeedLink ni Telegram y no representan ventaja garantizada antes de la onda S. «Alta» es confianza por asociación, no intensidad sentida.

En la ventana de Istmina del 27-sep también aparece el evento caribeño `us6000ty0q`. Con 8 se producen tres detecciones: el evento caribeño, una repetición compatible con su coda y el de Istmina. Con 10 quedan dos: se elimina la repetición de las 21:53:53 sin perder ninguno de esos eventos. La coincidencia del evento caribeño se hace retrospectivamente, por tiempos de llegada y catálogo; no se presupone que las estaciones sintieran un movimiento perceptible para personas.

| Perfil en las seis ventanas de ajuste | Disparos por estación (suma) | Detecciones (suma) | Eventos objetivo conservados |
|---|---:|---:|---:|
| Base: ON 5, confirmación 8 | 123 | 8 | 4/4 |
| Confirmación 6, ON 5 | 123 | 11 | 4/4 |
| **Confirmación 10, ON 5** | **123** | **7** | **4/4** |
| ON 4, confirmación 8 | 190 | 8 | 4/4 |
| ON 6, confirmación 8 | 102 | 8 | 4/4 |

Elevar ON a 6 reduce disparos sueltos, pero no elimina la repetición. Bajar confirmación a 6 añade dos detecciones sin coincidencia y otra repetición. Se conserva ON 5 para no estrechar también el inicio de detección en esta muestra pequeña.

### Controles, resultados negativos y límites

- `control1`: 27-sep 09:57–10:12. Ambos umbrales producen una detección compatible con `SGC2026taojuu` y otra sin coincidencia; esta última baja de alta a media con 10. Por tanto, esta ventana **no es un negativo puro**.
- `control2`: 28-sep 17:57–18:12. Cero detecciones con todos los perfiles.
- `background-hour`: 28-sep 01:57–02:57. Una detección alta sin coincidencia, a las 02:53:14, con ambos umbrales.
- En las diez ventanas completas quedan **dos detecciones sin coincidencia** con el ajuste elegido. No se etiquetan automáticamente como falsas: puede haber eventos no catalogados o limitaciones del emparejamiento. Tampoco se afirma una tasa de falsas alarmas por día ni sensibilidad poblacional a partir de 153 minutos.
- Los siete objetivos se conservan, pero la selección es pequeña y no aleatoria. Es una calibración preliminar, especialmente débil para sismos pequeños muy próximos a Medellín, cambios de ruido diario y otros mecanismos/profundidades. Antes de ampliar el modelo de intensidad se necesita evaluación continua con días completos y etiquetado independiente.

Ver `comparison.json` y `comparison.log` para todas las coincidencias, estaciones y tiempos; cada `*-perfil.json` conserva la traza de actualizaciones y todos los disparos. Las solicitudes y hashes están dentro de cada resultado. `data-sources.json` describe los catálogos y metadatos usados.

## Intensidad: reemplazo propuesto de `sources.priority()`

La regla actual puede marcar crítica cualquier M7 aunque esté muy lejos, y tratar igual magnitudes de distintas escalas. Propongo que la prioridad dependa de una **intensidad esperada en Medellín**, con nombre/versión de modelo, tipo de magnitud, distancia y un indicador de aplicabilidad. En este PR la propuesta queda documentada; no se sustituye silenciosamente la regla operativa por una ecuación aún no validada localmente.

Una candidata regional es la relación de Gómez-Capera et al. para sismos corticales de los Andes colombianos, reproducida como ecuación (8) en [Gómez-Capera et al. (2022)](https://bgo.ogs.it/sites/default/files/pdf/bgo00386_Gomez.pdf):

```text
I = -1.92 + 2.33 Mw - 0.0021 R - 3.68 log10(R)
R = sqrt(distancia_epicentral_km² + 10²)
```

La profundidad fija de 10 km pertenece a esa formulación. No debe reemplazarse por la profundidad real sin recalibrar, ni aplicarse a Los Santos profundo como si fuera un sismo cortical. Falta revisar en el conjunto original los límites de magnitud/distancia y la dispersión, y contrastar predicciones con intensidades del valle de Aburrá antes de habilitarla.

Como contraste con dispersión explícita está la IPE hipocentral de [Allen, Wald y Worden (2012)](https://link.springer.com/article/10.1007/s10950-012-9278-7), con coeficientes verificables en [OpenQuake](https://docs.openquake.org/oq-engine/3.0/_modules/openquake/hazardlib/gsim/allen_2012_ipe.html):

```text
R = sqrt(distancia_epicentral_km² + profundidad_km²)
rM = -0.209 + 2.042 exp(Mw - 5)
I = 2.085 + 1.428 Mw - 1.402 ln(sqrt(R² + rM²))
    + 0.078 max(0, ln(R / 50))
sigma_I = 0.82 + 0.37 / (1 + (R / 22.9)²)
```

El artículo abarca Mw 5,0–7,9, regiones corticales activas y distancias menores de 300 km; no valida por sí mismo Medellín ni sismos profundos/subducción. No se convierte ML/mb a Mw sin una relación regional respaldada. Profundidad o magnitud ausentes devuelven «estimación no disponible», nunca intensidad cero.

Diseño propuesto para una siguiente implementación:

1. Ejecutar ambas candidatas en modo de comparación sin afectar avisos, solo dentro de sus dominios verificados. Para eventos fuera de dominio conservar explícitamente la prioridad heredada y marcar el motivo.
2. Reunir intensidades observadas **en Medellín/Aburrá**, no el total mundial de testimonios EMSC; separar validación por evento para no mezclar observaciones del mismo sismo entre ajuste y prueba. Medir sesgo, error absoluto, cobertura de incertidumbre y omisiones de eventos sentidos. Añadir un término de sitio solo con evidencia local.
3. Como política inicial a evaluar, I esperada ≥ V sería crítica; III–IV, informativa; menor que III, silenciosa. Estos cortes son una propuesta de notificación, no coeficientes publicados ni umbrales de daño. Mostrar incertidumbre si cruza un corte; no reducir un aviso crítico basándose solo en una extrapolación.
4. Para profundos/subducción seleccionar una GMPE apropiada y convertir PGA/PGV a intensidad con validación local. Evitar extrapolar la ecuación cortical a todo el catálogo.

## Estaciones cercanas a Medellín

Se consultaron metadatos de SGC/EarthScope y el inventario **actual** de streams de `rtserve.iris.washington.edu`, guardado en `seedlink-cm.txt` (29-sep). Además de HEL, hay candidatas en el archivo del SGC:

| Estación y canal | Latitud, longitud | Distancia a Medellín | Evaluación |
|---|---|---:|---|
| CM.CBOC.00.HHZ | 5,864333; -76,012167 | 65,2 km | Primera candidata al suroeste |
| CM.RIO2C.00.HHZ | 5,421100; -75,710400 | 93,3 km | Complementa cobertura al sur |
| CM.HI8C.00.HHZ | 7,125510; -75,680200 | 98,4 km | Candidata al norte |
| CM.HI5C.00.HHZ | 7,152660; -75,658360 | 101,2 km | Muy próxima a HI8C: un mismo grupo si se agregan ambas |
| CM.NOR.00.HHZ | 5,563500; -74,869167 | 108,3 km | Complementa cobertura al sureste |
| CM.DBB.00.HHZ | 7,018000; -76,210000 | 111,4 km | Complementa cobertura al noroeste |
| CM.QUBC.00.HHZ | 5,748754; -76,519086 | 119,1 km | Candidata hacia Chocó |

**Ninguna de estas siete aparece en el inventario de streams CM consultado en IRIS.** Se conservan las 11 estaciones en producción: añadir entradas a `STATIONS` no crearía un flujo de datos. Una época de metadatos abierta tampoco acredita disponibilidad de formas de onda ni operación continua.

Priorizaría CBOC y NOR/DBB si el SGC ofrece acceso SeedLink autorizado o retransmisión. Antes de activarlas: verificar endpoint/selector, latencia p95, huecos y disponibilidad por al menos siete días; reproducir sismos y ruido local con el mismo pipeline; contar agrupaciones geográficas, no simplemente canales, y revisar posibles fuentes industriales/volcánicas. El puerto 8080 del archivo FDSN sirve para estas pruebas, no reemplaza automáticamente un servicio de baja latencia. No se verificó el servicio desde Azure.

## SGC desde Azure: alternativa al 403

La alternativa inmediata implementada es **USGS + EMSC**, habilitando `SISMOALERT_SGC_ENABLED=0` en `/etc/sismoalert.env`. Desactiva biweekly tanto en búsquedas como en el fondo del mapa; `/sgc-sismos` informa `available=false` y el motivo. No se rotulan datos USGS/EMSC como datos SGC. El websocket EMSC mantiene sus avisos sin esperar el ciclo de búsqueda. Esta combinación puede omitir eventos pequeños publicados solo por SGC: los replays de validación incluyen dos eventos cuya mejor coincidencia proviene de SGC.

Para conservar el catálogo SGC, propongo solicitar al SGC habilitación de la IP fija de salida de Azure o un endpoint institucional admitido. Si autoriza un distribuidor intermedio, usar un colector propio en una red aceptada que consulte con caché y publique por HTTPS un snapshot de esquema fijo, con `source=SGC`, ID original, hora de origen, hora de obtención y fecha de generación. Azure debe verificar antigüedad, límite de tamaño y esquema, conservar el último snapshot válido y mostrar «SGC desactualizado» si vence. Un endpoint fijo, autenticado y sin parámetros de URL arbitraria evita convertirlo en un proxy abierto.

No se despliega ese colector ni se automatiza un navegador para sortear el 403. `archive.sgc.gov.co` permanece apagado: no se asume que sea una alternativa autorizada. Que biweekly responda desde este equipo no demuestra disponibilidad desde Azure.

## Pruebas

- `python -m unittest discover -s tests -v`: 39 pruebas en `tests.log`, incluidos callbacks concurrentes, revisiones de ubicación, eventos EMSC repetidos, recuperación, pérdida de cola, 429/400, huecos de señal y conteo diario mayor de 30.
- Actualizador probado con repositorios Git desechables y simulaciones de sudo/systemd/red: fetch fallido, rama incorrecta, divergencia, cambios locales, dependencias nuevas, sintaxis inválida, permiso ausente, éxito, cambios solo de docs y rollback tras fallo de salud.
- `sh -n linux/actualizar.sh linux/instalar_servicio.sh`, compilación Python y `node tests/test_ui.js` (sintaxis de scripts y textos de estado).
- No se enviaron mensajes reales de Telegram ni se instaló/reinició un servicio real. Las pruebas simuladas no sustituyen una comprobación de la unidad endurecida en Ubuntu tras aprobar el despliegue.
