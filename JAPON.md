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
  con la señal de EarthScope de nuestras estaciones y la sensibilidad de cada sensor.
- **Validación** con el 25 % más reciente de los sismos (no usado para ajustar): a los 30 s,
  desviación 0,24 y 97 % dentro de ±0,5; a los 5 s, 0,34 y 90 %. Los de M≥6 salen bajos
  (−0,5 a los 30 s): Panamá llega a 6,6 a los 2 min y el Mw7,5 de Venezuela de junio a 6,4.
  Casi no hay sismos menores de M4 en la validación: ahí la magnitud no está comprobada.

## Evaluación por sitio: ¿sirvió la alerta en Medellín? (22-oct-2026)

Meier (2017, *How "good" are real-time ground motion predictions from Earthquake Early
Warning systems?*, JGR 122:5561, doi:10.1002/2017JB014025) propone juzgar un sistema de alerta
por lo que le importa a quien la recibe: si avisó antes de que en su sitio se superara una
intensidad, y si avisó cuando no hacía falta. `tools/evaluar_alertas.py` lo hace para Medellín:

- **La verdad es HEL**: para cada sismo se baja su señal de EarthScope, se pasa a velocidad y
  aceleración y se calcula la MMI y el instante en que cruza 2, 3 y 4 (Worden et al., 2012;
  la MMI sale de la PGV, como en ShakeMap 4). `intensidad.py` tiene las ecuaciones.
- Para cada umbral, cada sismo es acierto (aviso antes del cruce, con su tiempo de aviso),
  tarde, perdido, falsa (aviso sin que HEL llegara al umbral, o sin sismo) o correcto sin
  aviso. El aviso sale 15 s después del disparo y no se puede cancelar.
- **Opción A**, el sistema como está: avisa toda detección de nivel alta o media (o cualquiera).
- **Opción B**, cota ideal: al detectar se supone conocido el sismo del catálogo, se predice la
  MMI en Medellín (Allen, Wald y Worden, 2012) y se avisa si P(MMI > umbral) > p*. "Red ideal":
  la detección llega con la P a la estación más cercana que vota.

Resultados con el registro de la VM (29-sep a 21-oct, 3.421 sismos, MMI medida en HEL para 491):

- Solo **un sismo se sintió en Medellín**: el Mw7,7 de Panamá del 9-oct, MMI 3,0 en HEL.
  Ningún otro pasó de 1,1 (ni los M4 de Chaparral ni de Istmina).
- **Panamá fue un acierto**: aviso 56 s antes de MMI 2 y 161 s antes de MMI 3, con los dos
  asociadores. La red ideal da 54 y 159 s: en este sismo no se perdió tiempo.
- **Opción A: casi todo es falsa para Medellín.** Con umbral MMI 2: 873 falsas (ventana, alta o
  media), 517 con el bayesiano (−41 %). El aviso no dice cuánto va a temblar aquí.
- **Opción B: de cientos a 0-6 falsas.** MMI 2 con p* = 0,3: 3 falsas (réplicas de Panamá) y el
  mismo acierto; MMI 3 con p* ≥ 0,5: ninguna. Esto es lo que vale la magnitud preliminar.
- La ecuación de intensidad se pasa en HEL: Panamá prevista 4,3 y medida 3,0; su réplica M6,6,
  2,6 y 1,1. HEL está en roca a 2.857 m; el valle probablemente sintió más. Un caso no basta
  para calibrar.

Con un solo sismo sentido esto no es estadística: hace falta pasar años de archivo con sismos
sentidos en Medellín. Uso:

```
python tools/evaluar_alertas.py REGISTRO.json.gz --catalogos cat.pickle --obs obs.json --repasos repasos.pickle
```

## Pendiente

1. Correrlo en la VM de prueba (desde el 22-oct-2026) y comparar con `disparos.jsonl` y los
   catálogos.
2. Término de amplitud en la verosimilitud del ubicador (sigma 0,7 en el IPF) y en la prueba
   de "mismo sismo": ya hay amplitudes en unidades físicas. Evaluarlo con amplitudes medidas
   desde la señal archivada de los disparos de la VM.
3. Nivel "baja" (HEL sola): el bayesiano da más (231 frente a 86) porque ya no esconde disparos
   de HEL dentro de otras detecciones; la mitad son sismos reales. Decidir cómo avisarlos.
4. PLUM para Medellín: intensidad en tiempo real en HEL (a 8 km) como segundo camino de alerta.
5. Métricas al estilo JMA en el informe diario (aciertos de ±1 grado de intensidad, tiempo de
   la primera alerta desde el origen).
