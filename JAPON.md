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
| `tests/prueba_japon.py` | Pruebas sintéticas (en el CI): ubicación, disparo de ruido, dos sismos simultáneos. |

**Todavía no está conectado al servidor**: las alertas en vivo siguen con el asociador de
siempre. Los parámetros nuevos están en `config.py` (`UBICADOR_*`, `ASOCIADOR_*`).

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

## Pendiente

1. Conectar `BayesAssociator` al servidor con un interruptor en `config_local.py`, primero en
   la VM de prueba, comparando en paralelo con el actual.
2. Amplitudes en unidades físicas (sensibilidad de cada sensor) para el término de amplitud del
   IPF y una magnitud preliminar: mediana de las 5 más cercanas, sin estaciones a más de
   150 km de la más cercana ni a más de 700 km (lecciones del falso M7,3 de Torishima, 2020).
3. Nivel "baja" (HEL sola): el bayesiano da más (231 frente a 86) porque ya no esconde disparos
   de HEL dentro de otras detecciones; la mitad son sismos reales. Decidir cómo avisarlos.
4. PLUM para Medellín: intensidad en tiempo real en HEL (a 8 km) como segundo camino de alerta.
5. Métricas al estilo JMA en el informe diario (aciertos de ±1 grado de intensidad, tiempo de
   la primera alerta desde el origen).
