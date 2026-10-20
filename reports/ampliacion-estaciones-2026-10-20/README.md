# Ampliación de recepción · 20 de octubre de 2026

Se incorporan cinco canales públicos de EarthScope como **observación, sin alertas**.
Las 11 estaciones, coordenadas, umbrales y grupos del detector se conservan.

| Canal | País / territorio | Muestreo | Paquetes / 60 s | Retraso observado, mínimo–máximo |
| --- | --- | ---: | ---: | ---: |
| EC.TULM..HHZ | Ecuador | 100 Hz | 12 | 1,0–2,9 s |
| TC.PIRO..HHZ | Costa Rica | 100 Hz | 20 | 4,4–9,0 s |
| PR.ACPR.00.HHZ | Aruba | 100 Hz | 13 | 7,4–15,8 s |
| EC.CHSH..HHZ | Ecuador | 100 Hz | 19 | 1,6–3,1 s |
| G.HDC.00.BHZ | Costa Rica | 20 Hz | 6 | 3,9–16,7 s |

Prueba realizada desde la VM de Azure durante 60 segundos, hasta aproximadamente
21:41:38 UTC. Se recibieron miniSEED reales con el mismo cliente SeedLink de la
aplicación, en una sola conexión de prueba. No hubo huecos de más de un segundo
entre paquetes recibidos ni errores en esa ventana. Esto no demuestra continuidad
futura ni valida la sensibilidad del detector para esas señales.

También se probó CU.BCIP.00.BHZ (Panamá): no recibió paquetes durante los 60 segundos,
por lo que no se incorpora. La lista de canales anunciados no basta para demostrar
recepción. No se encontraron más estaciones CM con datos recientes en el inventario
de este proveedor consultado a las 21:38:59 UTC. Eso no implica que el SGC no tenga
otras estaciones: su catálogo de metadatos y su visor no equivalen a acceso SeedLink.

## Fuentes y selección

- [Servicio SeedLink de EarthScope](https://docs.earthscope.org/service/seedlink):
  servidor público y restricciones de conexiones. Producción conserva una conexión.
- [Inventario público de streams](https://rtserve.earthscope.org/streams/json):
  filtrado por canales verticales HHZ y BHZ; cruce con metadatos de canal abiertos.
- [Metadatos FDSN de EarthScope](https://service.earthscope.org/fdsnws/station/1/):
  coordenadas, canal, orientación y muestreo. Consulta regional: latitud −4 a 15,
  longitud −85 a −65, canales HHZ/BHZ vigentes el 20-oct-2026, sin acceso restringido.
- [Visor del SGC](https://trazas.sgc.gov.co/): permite visualizar trazas; no se
  identificó allí un servicio documentado de ondas en vivo para este cliente.

Se excluyeron PULU y ANTS por el ruido ya documentado en la calibración anterior;
también canales con orientación o muestreo inconsistentes. Las nuevas estaciones
son regionales, a aproximadamente 663–1029 km de Medellín. No aportan nuevas
estaciones locales ni aumentan por sí solas la capacidad de alerta.

## Separación y pruebas

- `config.STATIONS` mantiene las 11 estaciones del detector; las cinco nuevas
  están en `OBSERVATION_STATIONS`.
- La recepción valida red, estación, ubicación y canal. `StationMonitor` solo
  registra llegada de paquetes y hora de la última muestra. No ejecuta STA/LTA.
- Los avisos de salud de Telegram siguen tomando las estaciones del detector:
  una estación de observación activa no puede ocultar su caída total.
- La API, las tarjetas y los marcadores incluyen el papel de cada estación.
- 49 pruebas Python y cinco suites JavaScript aprobadas. Las ocho pruebas nuevas
  cubren paquetes antiguos, fuera de orden y vacíos; aislamiento del asociador;
  identidad de canal; paso de HEL al asociador; salud de alertas y una única conexión.
- Interfaz revisada en un servidor local con **datos simulados**: 16 tarjetas,
  cinco etiquetas de observación, navegación a TULM y sin errores JavaScript.
  La captura local no acredita la sesión autenticada del usuario en Azure.
- No se enviaron mensajes manuales de Telegram durante esta ampliación.

Queda pendiente aclarar si el aviso reportado «Ninguna estación tiene datos recientes»
aparece en Telegram o en la página del usuario. Esa frase exacta pertenece al aviso
de salud de Telegram. No se da el problema por resuelto con esta ampliación.
