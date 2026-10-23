# Rama Japon: lo que aprendimos del sistema de alerta temprana de Japón

Esta rama adapta a SismoAlert los métodos que la agencia meteorológica de Japón (JMA) puso en
operación después del terremoto de Tohoku (2011), cuando su sistema dio decenas de alarmas
falsas por juntar disparos de sismos distintos, igual que nos pasa a nosotros.

Fuentes:

- Tamaribuchi, Yamada y Wu (2014). *Método de ubicación que separa sismos simultáneos para
  la alerta temprana* (en japonés). Zisin 67, 41–55. doi:10.4294/zisin.67.41. Es el método
  IPF (*Integrated Particle Filter*): con las 72 alertas de marzo-abril de 2011, las falsas
  bajaron de 22 a 0.
- Kodera et al. (2021). *Developments of the Nationwide Earthquake Early Warning System in
  Japan After the 2011 Mw9.0 Tohoku-Oki Earthquake*. Front. Earth Sci. 9:726045.
  doi:10.3389/feart.2021.726045. Balance de 10 años: IPF (2016), PLUM (2018), cables
  submarinos S-net.

## Qué hay en la rama

| Archivo | Qué hace |
|---|---|
| `ubicador.py` | Ubica el sismo buscando en una malla el epicentro más probable con: sismicidad previa, zona de Voronoi de la primera estación, tiempos de los disparos y estaciones calladas que ya debieron disparar. Cada término tiene un piso para datos anómalos. |
| `asociador.py` | `BayesAssociator`: misma interfaz que `detector.Associator`. Un disparo se suma a un sismo solo si este lo explica; si no, abre otro. Funde sismos partidos y saca disparos ajenos. |
| `tiempos_p.json` | Tiempos de la onda P (modelo IASP91) por distancia y profundidad. Lo genera `tools/tabla_tiempos.py`. |
| `sismicidad_previa.json` | 65.863 sismos del USGS (M≥2,5 desde 1990) contados en celdas de 0,5° × 50 km. Lo genera `tools/sismicidad_previa.py`. |
| `tools/evaluar_asociador.py` | Pasa los disparos de un registro por los dos asociadores y los compara contra los catálogos. |
| `magnitud.py` | Magnitud preliminar: amplitud máxima en los primeros 5 y 30 s de cada disparo, magnitud por estación y mediana de las más cercanas. |
| `magnitud.json` | Coeficientes calibrados y sensibilidad de cada sensor. Lo genera `tools/calibrar_magnitud.py`. |
| `tests/prueba_japon.py` | Pruebas sintéticas (en el CI): ubicación, disparo de ruido, dos sismos simultáneos, magnitud. |

**Cómo activarlo**: en `config_local.py` de la máquina, `ASOCIADOR = "bayesiano"` (por
omisión es `"ventana"`, el de siempre) y reiniciar el servicio. Cada detección guarda entonces
su ubicación en `ubicacion`. Con cualquiera de los dos, el servidor anota todos los disparos
en `datos/disparos.jsonl`, también los que no llegan a detección, para poder volver a pasar un
periodo por ambos asociadores. Los parámetros nuevos están en `config.py` (`UBICADOR_*`,
`ASOCIADOR_*`).

`linux/actualizar.sh` sigue la rama en que esté la máquina, así que una VM de prueba puesta en
`Japon` se actualiza desde `Japon`.

## Resultados (registro de la VM, 25-sep a 21-oct de 2026)

1.033 detecciones, 3.000 disparos de las 11 estaciones que votan, contra los catálogos del SGC,
USGS y EMSC. Una detección es *real* si al menos 2 de sus disparos fuertes encajan con la
onda P de un sismo de catálogo (−10 a +15 s); la regla del servidor (basta una estación)
resultó demasiado laxa para comparar.

| | Actual (ventana de 120 s) | Bayesiano |
|---|---|---|
| Detecciones | 968 | 750 |
| Reales | 419 | 404 |
| **Falsas** | **549** | **346 (−37 %)** |
| Falsas de nivel "alta" | 271 | 157 (−42 %) |
| Disparos ajenos dentro de las detecciones reales | 23 % | 7 % |
| "Alta" en que el disparo de HEL no era del sismo | 33 | 9 |
| Sismos de catálogo detectados | 411 | 396 |

Error del epicentro (bayesiano) frente al catálogo: mediana de 170 km para sismos con una
estación a menos de 300 km, 247 km para los de fuera de la red. Con pocas estaciones la
ubicación es aproximada; su valor está en decidir qué disparos son del mismo sismo.

## Qué adaptamos y por qué

Nuestra red tiene ~10 estaciones a cientos de km entre sí; la de Japón, ~1.000 a decenas de
km. Varios parámetros del artículo no sirven tal cual (medido con nuestros datos):

- **Búsqueda en malla** de 0,2° en vez de filtro de partículas: con tan pocas estaciones es
  exacta y tarda ~0,2 s por disparo.
- **σ = 4 s** en vez de 1,5 s: es el error medido de nuestros disparos STA/LTA frente a la P
  teórica en sismos confirmados.
- **Piso de datos anómalos con tope de 0,2** (en el original llega a 1) y **sismicidad previa
  a medio peso**: sin esto, un disparo de ruido en PRV llevaba el epicentro de Chaparral a
  Panamá, porque Panamá tiene mucha sismicidad y los desajustes de las demás estaciones
  costaban casi nada.
- **Estaciones calladas**: el original castiga a las 5 más cercanas; aquí esas pueden estar a
  500 km. Se castiga la callada que esté más cerca que la segunda estación que sí disparó.
- **Zona de Voronoi** más ancha (100 km) y con piso, porque el primer disparo a veces es
  ruido (HEL disparó 11 s antes del M4,0 de Istmina del 26-sep).
- **Tiempos IASP91**: `traveltime.py` daba 5 s para la P de un sismo a 150 km bajo la estación
  (el modelo real da 20 s). Afecta al Nido de Bucaramanga. `traveltime.py` no se cambió.
- **Fusión por ubicación conjunta**: con pocas estaciones cada mitad de un sismo partido se
  ubica mal y ninguna explica a la otra; juntas sí encajan.
- **Depuración**: con 3 o más disparos fuertes que encajan, los que no encajan salen del sismo.

## Magnitud preliminar (22-oct-2026)

Como en la JMA, cada estación da una magnitud con su amplitud máxima y su distancia, y la del
sismo es la mediana de las 5 más cercanas al epicentro, sin las que estén más de 150 km más
lejos que la más cercana ni a más de 700 km (el falso M7,3 de Torishima de 2020 salió de
estaciones lejanas). Va en `det["magnitud"]` (`valor`, `n`, `incertidumbre`, `estaciones`) y en
el mensaje, y se recalcula cada 5 s mientras llega la parte fuerte de la señal.

- **Desplazamiento en 0,2-5 Hz**, como la JMA. La velocidad en la banda del detector (2-10 Hz)
  se satura: daba M5,1 para el Mw7,7 de Panamá del 9-oct. Si el desplazamiento no supera 3
  veces el ruido (sismos pequeños) se usa la velocidad, también como la JMA.
- **Calibración propia** (`tools/calibrar_magnitud.py`): 1.633 sismos del USGS (M≥3, un año)
  y 978 pequeños del SGC (M≥2) cerca de nuestras estaciones, con la señal de EarthScope y la
  sensibilidad de cada sensor. Cada medio grado de magnitud pesa lo mismo. Una primera
  versión solo con el USGS (casi todo M4-5) salía chata y daba +1,3 de más en los M<3.
- **Validación** con el 25 % más reciente de los sismos (no usado para ajustar): a los 30 s,
  desviación 0,35, 85 % dentro de ±0,5, sin sesgo apreciable de M3 a M7; a los 5 s, 0,49.
  Con los disparos reales de la VM (25-sep a 21-oct) y la ubicación del catálogo, el error
  mediano es −0,2 en M<3, 0,0 en M3-4, −0,3 en M4-5 y −0,1 en M≥5.
- **Con la ubicación del sistema** el error crece (|error| mediano 0,6; M4-5 −0,6, M≥5
  −1,0), porque un epicentro mal puesto cambia la distancia. Mejorar la ubicación mejora la
  magnitud.
- Con señal real, el Mw7,7 de Panamá del 9-oct llega a 7,3 a los 2 min (4,7 con solo HEL).

### Término de amplitud en el ubicador (probado, apagado)

La magnitud de cada estación frente a la del sismo (σ = 0,7) como término más de la
verosimilitud y de la prueba de "mismo sismo", con un ajuste: mientras no pasan 5 s del
disparo la amplitud solo es una cota inferior y únicamente castiga si ya es demasiado fuerte.
`tools/amplitudes_disparos.py` midió los 5.086 disparos de la VM con la señal archivada, y
`tools/evaluar_asociador.py --amplitudes` los repasa dando en cada instante la amplitud que
se conocía entonces.

| Registro de la VM | Sin término | Con término |
|---|---|---|
| Reales / falsas | 407 / 348 | 403 / 338 |
| Disparos ajenos en las reales | 7 % | 5 % |
| Error del epicentro, dentro de la red | 149 km | 203 km |
| Error del epicentro, fuera de la red | 248 km | 110 km |

Ayuda con los sismos lejanos y empeora los de dentro de la red, que son los que importan para
Medellín; con señal real llevó el M5,5 del Nido de Bucaramanga al Caribe. La razón: en los datos
de calibración los sismos pequeños están cerca y los grandes lejos, así que la fórmula no separa
bien magnitud y distancia (y mezcla ML del SGC con mb/Mw del USGS). Queda apagado
(`UBICADOR_AMPLITUD = False`); la magnitud no depende de esto.

## Evaluación por sitio: ¿sirvió la alerta en Medellín? (23-oct-2026)

La evaluación está separada de la alerta, en `evaluacion/` (ver su `README.md`): la alerta
solo escribe sus decisiones en `datos/decisiones.jsonl` (`decisiones.py`) y la evaluación las
juzga con las métricas de Meier (2017): intensidad real en cada sitio (suma vectorial de las
horizontales), tiempo de aviso hasta el cruce del umbral, sin cancelación, tolerancia ±0,5,
pseudo-ROC y CAR en vez de TN, y las detecciones falsas aparte. Medellín es HEL; los otros 10
sitios son las demás estaciones. La predicción de intensidad vive solo en la evaluación.

**Lote histórico** (113 sismos de 2015 a 2026: los 19 que llegaron a MMI 2 en HEL, 75 no
sentidos a los que la ecuación daba MMI ≥ 1,5 y 19 al azar; repasados con la señal archivada
del SGC por el detector, los dos asociadores y la magnitud de hoy). Con 15 s de latencia, en
Medellín y umbral MMI 2:

| Manera de avisar | TPR | Falsas | CAR | Aviso (mediana) |
|---|---|---|---|---|
| Sistema actual (alta o media, bayesiano) | 0,82 | 75 | 0,16 | 28 s |
| Magnitud del sistema, p* = 0,5 | 0,83 | 32 | 0,32 | 20 s |
| Magnitud del catálogo (ideal), p* = 0,5 | 0,86-0,88 | 11 | 0,63-0,67 | 25 s |
| Red ideal, p* = 0,5 | 0,88 | 12 | 0,66 | 26 s |

- Para Medellín, **la detección ya es casi tan rápida como la red ideal**; lo que separa al
  sistema del ideal es conocer el sismo (magnitud y ubicación). Con la magnitud del sistema
  las falsas bajan a menos de la mitad sin perder aciertos; con la del catálogo, a un séptimo.
- En los 11 sitios, la red ideal acierta 0,80-0,85 frente a 0,68-0,77 de la detección real:
  la demora pesa en los sitios lejanos (Muisne Mw7,8: alerta a +112 s con la ventana, la red ideal +25 s,
  porque OTAV y PUYO valen por una confirmación).
- La magnitud del sistema empieza baja en los sismos que más se sienten (ΔMMI +1,0 a +1,6
  con más de 30 s de aviso en sitios con MMI 3-4) y se corrige al acercarse el cruce.
- San José del Palmar Mw7,4 (ago-2026, MMI 3,9 en HEL): MMI 2 a los +27 s del origen y la
  alerta a +26 s; con la latencia real llega tarde a Medellín.
- La ecuación de intensidad se pasa en HEL (Bello M4,6 de 2024: 4,2 prevista, 2,4 medida).
- Las falsas del lote dependen de cómo se escogieron los no sentidos: sirven para comparar
  maneras de avisar, no como tasa absoluta.

**Registro de la VM** (29-sep a 21-oct, repasando los disparos guardados, sin magnitud):
solo el Mw7,7 de Panamá llegó a MMI 2 en HEL (3,1), con 71 s de aviso. Detecciones sin sismo
de nivel alta o media: 222 con el bayesiano y 497 con la ventana (10 y 22 por día).

## Pendiente

1. Correrlo en la VM de prueba (desde el 22-oct-2026) y comparar con `disparos.jsonl` y los
   catálogos.
2. Término de amplitud: probado y apagado (ver arriba). Para retomarlo hace falta una relación
   de atenuación que separe bien magnitud y distancia (p. ej. ajustada dentro de cada sismo,
   como la ML) y una sola escala de magnitud.
3. Nivel "baja" (HEL sola): el bayesiano da más (231 frente a 86) porque ya no esconde disparos
   de HEL dentro de otras detecciones; la mitad son sismos reales. Decidir cómo avisarlos.
4. PLUM para Medellín: intensidad en tiempo real en HEL (a 8 km) como segundo camino de alerta.
5. Métricas al estilo JMA en el informe diario (aciertos de ±1 grado de intensidad, tiempo de
   la primera alerta desde el origen).
