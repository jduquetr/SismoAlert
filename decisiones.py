"""Registro de decisiones de la alerta: lo único que la evaluación lee de ella.

Cada vez que la alerta declara o cambia una detección se escribe una línea en
datos/decisiones.jsonl con lo que se decidió y a qué hora salió. La evaluación
(evaluacion/, ver su README) juzga la alerta solo con este registro, los catálogos y las
formas de onda archivadas; nunca la importa ni cambia su comportamiento. El repaso con señal
archivada (evaluacion/repaso.py) escribe el mismo formato con origen "repaso".

Formato (versión 1), una línea JSON por decisión:

- v: versión del formato; origen: "vivo" (la hora es la del reloj del servidor, con toda la
  latencia real) o "repaso" (la hora es la de la señal simulada; la evaluación le suma la
  latencia que se quiera estudiar);
- emitida: hora en que salió la decisión (ISO, UTC); evento: "nueva" o "actualizacion";
- id, nivel (alta, media, baja, catálogo), primer_disparo, estaciones ({estación: {onset,
  ratio}}), ubicacion y magnitud (null si el asociador no las da), descartada (motivo o null),
  asociador ("ventana" o "bayesiano");
- medellin: la intensidad prevista en Medellín y si hay alerta por ella, o null si la alerta no
  la calcula: {mmi, sigma, prob, fuente ("plum-HEL", "plum-<EST>", "pd-HEL", "magnitud"),
  alerta (bool), alerta_desde (ISO o null)} y, cuando la haya, observada ({mmi, cruces:
  {umbral: hora ISO}}, lo que ya midió HEL en tiempo real) y umbral (MMI de la alerta).
  Campo agregado el 23-oct-2026; las líneas anteriores no lo traen.
"""
import json
import logging

from obspy import UTCDateTime

import config
import store

log = logging.getLogger("decisiones")

VERSION = 1
ARCHIVO = store.DATA / "decisiones.jsonl"


def _json(o):
    return o.item() if hasattr(o, "item") else str(o)


def linea(det, evento, hora, origen="vivo", asociador=None):
    """La decisión como diccionario del formato (sin escribirla)."""
    return {"v": VERSION, "origen": origen, "emitida": str(hora), "evento": evento,
            "id": det["id"], "nivel": det.get("level"),
            "primer_disparo": str(det.get("first_onset")),
            "estaciones": det.get("stations", {}), "ubicacion": det.get("ubicacion"),
            "magnitud": det.get("magnitud"), "descartada": det.get("discarded"),
            "asociador": asociador or config.ASOCIADOR, "medellin": det.get("medellin")}


def registrar(det, evento, hora=None, archivo=ARCHIVO):
    """Anota una decisión. Un error al escribir nunca detiene la alerta."""
    try:
        archivo.parent.mkdir(parents=True, exist_ok=True)
        with open(archivo, "a", encoding="utf-8") as f:
            f.write(json.dumps(linea(det, evento, hora or UTCDateTime()), default=_json,
                               ensure_ascii=False) + "\n")
    except Exception:
        log.exception("No se pudo registrar la decisión de %s", det.get("id"))
