"""Genera estaciones_region.py: las estaciones de la región que transmiten en abierto.

Uso (desde la raíz del repo):
  python tools/estaciones_region.py                  # rectángulo México - norte de Perú
  python tools/estaciones_region.py N S E O          # otro rectángulo (grados)

Por qué así:
- Que una estación figure en un catálogo (ISC, FDSN) no dice que transmita. Lo dice el
  servidor SeedLink: a INFO STREAMS responde, canal por canal, la hora del último dato.
  Entra la estación cuyo canal vertical tiene un dato de hace menos de VIVA_MIN minutos.
- Servidores públicos: EarthScope (rtserve, el mismo que ya usa el detector) y GEOFON.
  Raspberry Shake no ofrece SeedLink público. Solo se usan los que hablan SeedLink 3.1, que
  es lo que entiende seedlink.py: GEOFON anuncia solo la versión 4, responde OK a las
  órdenes 3.1 pero no manda datos (probado el 9-oct) y su conexión se caía cada 2 min.
- Canal: el vertical de mayor muestreo que esté en vivo (HHZ, luego BHZ...). El
  acelerómetro (HNZ/ENZ) solo si no hay otro.
- No toca las estaciones principales de config.CORE_STATIONS.
- Grupos: estaciones a menos de GRUPO_KM entre sí valen por una confirmación, como OTAV y
  PUYO hoy. Así las redes densas (Puerto Rico tiene decenas) no confirman solas un sismo
  si algún día se les deja votar.

La lista es una foto: una estación puede caerse o volver. Se regenera cuando haga falta.
"""
import datetime as dt
import json
import math
import re
import socket
import struct
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config  # noqa: E402

SERVIDORES = [
    ("rtserve.iris.washington.edu:18000", "https://service.earthscope.org/fdsnws"),
    ("geofon.gfz-potsdam.de:18000", "https://geofon.gfz-potsdam.de/fdsnws"),
]
VIVA_MIN = 10
GRUPO_KM = 150
PREFERENCIA = ["HHZ", "BHZ", "EHZ", "SHZ", "HNZ", "ENZ", "HLZ"]
RECTANGULO = (23.631, -7.290, -61.992, -104.883)  # norte, sur, este, oeste


def info_streams(servidor):
    """XML de INFO STREAMS. Cada paquete: 8 bytes ("SLINFO  ", o "SLINFO *" si siguen
    más) y un registro miniSEED de 512 bytes cuyo contenido es un trozo del XML."""
    host, port = servidor.split(":")
    s = socket.create_connection((host, int(port)), timeout=60)
    s.settimeout(120)
    f = s.makefile("rb")
    s.sendall(b"HELLO\r\n")
    banner = f.readline().decode("latin-1")
    f.readline()
    if "SLPROTO:3.1" not in banner:
        s.close()
        return None
    s.sendall(b"INFO STREAMS\r\n")
    trozos = []
    while True:
        cab = f.read(8)
        if len(cab) < 8:
            break
        if cab.startswith(b"ERROR"):
            raise RuntimeError(f"{servidor}: {cab!r}")
        reg = f.read(512)
        n = struct.unpack(">H", reg[30:32])[0]
        ini = struct.unpack(">H", reg[44:46])[0]
        trozos.append(reg[ini:ini + n])
        if cab[7:8] != b"*":
            break
    s.sendall(b"BYE\r\n")
    s.close()
    return b"".join(trozos).decode("latin-1")


def hora(texto):
    t = texto.replace("/", "-").replace("Z", "").replace(" ", "T")[:26]
    return dt.datetime.fromisoformat(t).replace(tzinfo=dt.UTC)


def coordenadas(fdsn, rect):
    n, s, e, o = rect
    url = (f"{fdsn}/station/1/query?minlat={s}&maxlat={n}&minlon={o}&maxlon={e}"
           f"&level=station&format=text&endafter={dt.date.today().isoformat()}")
    req = urllib.request.Request(url, headers={"User-Agent": "sismos-alerta/0.1"})
    with urllib.request.urlopen(req, timeout=180) as r:
        texto = r.read().decode("utf-8")
    out = {}
    for linea in texto.splitlines():
        if linea.startswith("#") or not linea.strip():
            continue
        c = linea.split("|")
        out[(c[0], c[1])] = (float(c[2]), float(c[3]), c[5].strip())
    return out


def km(a, b):
    r = math.pi / 180
    h = (math.sin((b[0] - a[0]) * r / 2) ** 2
         + math.cos(a[0] * r) * math.cos(b[0] * r) * math.sin((b[1] - a[1]) * r / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(h))


def main():
    rect = tuple(float(x) for x in sys.argv[1:5]) if len(sys.argv) >= 5 else RECTANGULO
    ahora = dt.datetime.now(dt.UTC)
    nucleo = {(net, sta) for sta, (net, *_) in config.CORE_STATIONS.items()}
    elegidas, descartes = {}, []

    for servidor, fdsn in SERVIDORES:
        xml = info_streams(servidor)
        if xml is None:
            print(f"{servidor}: no habla SeedLink 3.1; se omite", file=sys.stderr)
            continue
        meta = coordenadas(fdsn, rect)
        vivas = 0
        for m in re.finditer(r'<station name="([^"]+)" network="([^"]+)"[^>]*>(.*?)</station>', xml, re.S):
            sta, net, cuerpo = m.groups()
            if (net, sta) not in meta or (net, sta) in nucleo:
                continue
            canales = {}
            for c in re.finditer(r'location="([^"]*)" seedname="([^"]+)" type="D" begin_time="[^"]+" '
                                 r'end_time="([^"]+)"', cuerpo):
                loc, cha, fin = c.group(1), c.group(2), hora(c.group(3))
                atraso = (ahora - fin).total_seconds() / 60
                # Algún reloj de adquisición viene adelantado (año 2046): no cuenta como vivo
                if -5 <= atraso <= VIVA_MIN and cha in PREFERENCIA:
                    if cha not in canales or fin > canales[cha][1]:
                        canales[cha] = (loc, fin)
            cha = next((c for c in PREFERENCIA if c in canales), None)
            if not cha:
                continue
            lat, lon, sitio = meta[(net, sta)]
            if sta in elegidas and elegidas[sta]["net"] == net:
                continue  # la misma estación en los dos servidores: se queda la de EarthScope
            if sta in config.CORE_STATIONS or sta in elegidas:
                # El sistema identifica las estaciones por su código: dos con el mismo no caben
                descartes.append(f"{net}.{sta} (código repetido)")
                continue
            elegidas[sta] = {"net": net, "loc": canales[cha][0], "cha": cha, "lat": round(lat, 4),
                             "lon": round(lon, 4), "sitio": sitio, "servidor": servidor}
            vivas += 1
        print(f"{servidor}: {vivas} estaciones en vivo en la región", file=sys.stderr)

    # Grupos por cercanía: primero con las principales, después entre las nuevas. Se mide
    # contra la estación que fundó cada grupo, no contra cualquier miembro: si no, la cadena
    # de vecinas va estirando el grupo mucho más allá de GRUPO_KM.
    grupos = {}
    nucleo_pos = {s: v[3:5] for s, v in config.CORE_STATIONS.items()}
    semillas = {}  # grupo -> posición de la estación que lo fundó
    for sta, e in sorted(elegidas.items(), key=lambda kv: (-kv[1]["lat"], kv[1]["lon"])):
        pos = (e["lat"], e["lon"])
        cerca = sorted((km(pos, p), s) for s, p in nucleo_pos.items() if km(pos, p) <= GRUPO_KM)
        if cerca:
            grupos[sta] = config.CORE_GROUPS.get(cerca[0][1], cerca[0][1])
            continue
        cerca = sorted((km(pos, p), g) for g, p in semillas.items() if km(pos, p) <= GRUPO_KM)
        if cerca:
            grupos[sta] = cerca[0][1]
        else:
            grupos[sta] = sta
            semillas[sta] = pos

    lineas = [
        '"""Estaciones de la región que transmiten en abierto (generado por tools/estaciones_region.py).',
        "",
        f"Foto del {ahora:%Y-%m-%d %H:%M} UTC: canal vertical con dato de hace menos de {VIVA_MIN} min en",
        "el SeedLink de EarthScope o de GEOFON. No editar a mano: regenerar.",
        f"Rectángulo: norte {rect[0]}, sur {rect[1]}, este {rect[2]}, oeste {rect[3]}.",
        '"""',
        "",
        "# Estación -> (red, ubicación, canal vertical, lat, lon)",
        "REGIONAL_STATIONS = {",
    ]
    for sta, e in sorted(elegidas.items(), key=lambda kv: (kv[1]["net"], kv[0])):
        lineas.append(f'    {json.dumps(sta)}: ({json.dumps(e["net"])}, {json.dumps(e["loc"])}, '
                      f'{json.dumps(e["cha"])}, {e["lat"]}, {e["lon"]}),  # {e["sitio"][:48]}')
    lineas += ["}", "", "# Las que no salen del SeedLink de EarthScope (el de config.SEEDLINK_SERVER)",
               "REGIONAL_SERVERS = {"]
    for sta, e in sorted(elegidas.items()):
        if e["servidor"] != SERVIDORES[0][0]:
            lineas.append(f'    {json.dumps(sta)}: {json.dumps(e["servidor"])},')
    lineas += ["}", "", f"# Estaciones a menos de {GRUPO_KM} km entre sí (o de una principal) valen por una",
               "REGIONAL_GROUPS = {"]
    for sta in sorted(grupos):
        if grupos[sta] != sta or any(g == sta and s != sta for s, g in grupos.items()):
            lineas.append(f'    {json.dumps(sta)}: {json.dumps(grupos[sta])},')
    lineas += ["}", ""]
    if descartes:
        lineas += ["# Descartadas: " + ", ".join(descartes), ""]
    (ROOT / "estaciones_region.py").write_text("\n".join(lineas), encoding="utf-8")
    print(f"{len(elegidas)} estaciones -> estaciones_region.py; descartadas: {descartes or 'ninguna'}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
