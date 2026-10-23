# Evaluación de la alerta temprana

Esta carpeta juzga qué tan buena es la alerta. **No es parte de la alerta**: la alerta
(`server.py`, `detector.py`, `asociador.py`, `ubicador.py`, `magnitud.py`...) nunca importa
nada de aquí, y `tests/prueba_evaluacion.py` lo vigila en el CI. La evaluación sí usa la
alerta, pero como una caja negra, para repasar señal archivada.

```
   ALERTA (corre en la VM)                         EVALUACIÓN (esta carpeta)
   detector → asociador → magnitud                 catálogos (SGC, USGS, EMSC)
          │                                        señal archivada (EarthScope)
          ▼                                                 │
   decisiones.py ──► datos/decisiones.jsonl ──────────────► evaluar.py ──► informe
                       (el contrato)                        ▲
   repaso.py: la alerta alimentada con señal archivada ─────┘
              escribe el mismo formato, origen "repaso"
```

## El contrato: el registro de decisiones

`decisiones.py` (del lado de la alerta) escribe una línea en `datos/decisiones.jsonl` cada
vez que una detección se declara o cambia: hora de emisión, nivel, disparos, ubicación,
magnitud y asociador (el formato está en su docstring). Es lo único que la evaluación lee de
la alerta. El repaso escribe lo mismo con `origen: "repaso"` y la hora de la señal simulada.

## Las métricas (Meier, 2017)

Meier, M.-A. (2017). *How "good" are real-time ground motion predictions from Earthquake
Early Warning systems?* J. Geophys. Res. Solid Earth 122, 5561-5577.
doi:10.1002/2017JB014025

La idea: juzgar la alerta por lo que le importa a quien la recibe en un sitio, no por el error
de la magnitud o del epicentro. Lo que adoptamos (decisiones del 22-oct-2026):

- **La verdad está en cada sitio.** Los sitios son las estaciones de la red; Medellín es HEL
  (Santa Elena, a 8 km). Se baja su señal, se toma la **suma vectorial de las dos
  horizontales** y se calcula la MMI (Worden et al., 2012, con la PGV como ShakeMap 4) y el
  primer instante en que cruza cada nivel (`observado.py`).
- **Tiempo de aviso**: desde la alerta hasta que el sitio supera el umbral de intensidad (no
  hasta la onda S, ni desde el origen).
- **Una alerta no se cancela**: basta con que el criterio se cumpla una vez.
- **Tolerancia de ±0,5 MMI** (sección 4.3): una alerta para MMI 4 en un sitio que tuvo 3,7 es
  acierto; solo es falsa si quedó más de 0,5 por debajo, y solo es perdida si superó 4,5. El
  CSV trae también los límites estrictos.
- **Sin TN como medida**: dependen de qué sismos se escojan. Se resume con el pseudo-ROC
  normalizado por TP + FN (TPR = TP/(TP+FN), FPR = FP/(TP+FN)) y la tasa de alertas correctas
  CAR = TP/(TP+FP).
- **Las detecciones falsas (sin sismo) van aparte**, no dentro de la clasificación por sitio.
- **Latencia**: el artículo la ignora. Aquí se evalúa sin latencia y con la medida (15 s por
  omisión) para los repasos; el registro en vivo ya la trae.
- **ΔMMI frente al tiempo de aviso** (su figura 3): qué tan buena era la predicción mientras
  todavía servía.

Cuatro maneras de decidir la alerta para un sitio:

| Manera | Qué es | Equivale en el artículo a |
|---|---|---|
| sistema | La alerta como está: avisa toda decisión alta/media (o cualquier nivel). Solo Medellín | — |
| magnitud del sistema | Con la magnitud y ubicación de cada decisión se predice la MMI del sitio y se avisa si P(MMI > umbral) > p* | SPS |
| catálogo | En la primera decisión se supone conocido el sismo del catálogo | IFS (cota ideal) |
| red ideal | Como catálogo, pero la detección llega con la P a la estación más cercana | máximo tiempo de aviso |

La predicción de intensidad (`intensidad.py`, Allen, Wald y Worden, 2012) vive aquí: la
alerta todavía no predice intensidades. Se incorporará a la alerta solo si la evaluación
muestra que vale la pena (decisión del 22-oct-2026).

## Uso

```
# Registro en vivo de la VM (datos/decisiones.jsonl), con los catálogos del periodo
python -m evaluacion.evaluar --decisiones decisiones.jsonl --catalogos cat.pickle --obs obs.json

# Disparos ya guardados (sin señal, sin magnitud) -> decisiones
python -m evaluacion.repaso disparos datos/disparos.jsonl --salida decisiones_repaso.jsonl

# Lote histórico desde 2011 (ver lote_historico.py)
python -m evaluacion.lote_historico catalogo --salida lote/cat.pickle
python -m evaluacion.lote_historico seleccionar --catalogos lote/cat.pickle --obs lote/obs.json --salida lote/sismos.pickle
python -m evaluacion.repaso senal lote/sismos.pickle --salida lote/decisiones.jsonl
python -m evaluacion.evaluar --decisiones lote/decisiones.jsonl --catalogos lote/cat.pickle --universo lote/sismos.pickle --obs lote/obs.json
```

## Archivos

| Archivo | Qué hace |
|---|---|
| `evaluar.py` | Lee decisiones, catálogos e intensidades y saca el informe y el CSV |
| `metricas.py` | Clasificación con tolerancia, pseudo-ROC, CAR, tabla de ΔMMI |
| `observado.py` | Intensidad y cruces de umbral en cada sitio, con caché |
| `intensidad.py` | Ecuaciones de intensidad prevista y observada |
| `catalogo.py` | Sismos únicos y qué sismo explica cada decisión |
| `repaso.py` | La alerta en pseudo-tiempo-real con señal archivada o con disparos |
| `lote_historico.py` | Catálogo desde 2011 y selección de sismos para el repaso |

## Limitaciones conocidas

- HEL está en roca a 2.857 m: el valle de Medellín probablemente siente más. La ecuación de
  intensidad sobrestimó en HEL (Panamá: 4,3 prevista, 3,1 medida).
- Los sensores son de banda ancha y pueden saturarse con MMI ≳ 6 (se marca).
- El repaso histórico usa las estaciones de hoy; en años pasados faltan algunas.
- La API del SGC solo devuelve sismos recientes: el lote histórico usa el USGS (M ≥ 3,5), así
  que faltan los sismos locales pequeños. EarthScope solo guarda las horizontales de la red CM
  desde 2026; antes se piden al SGC (`fuentes.py`), que no las tiene para 2011-2014.
- En el lote, las falsas dependen de cómo se escogieron los no sentidos: sirven para comparar
  maneras de avisar, no como tasa absoluta (para eso, el registro en vivo).
