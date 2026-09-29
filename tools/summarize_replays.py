"""Asocia los replays a los catálogos congelados; no descarga ni envía avisos."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from obspy import UTCDateTime
import config
import sources
import server

REPORT = ROOT / 'reports/revision-2026-09-29'


def catalog_events():
    events = []
    for feature in json.loads((REPORT/'sgc_recent.txt').read_text())['features']:
        p = feature['properties']
        lon, lat, depth = feature['geometry']['coordinates']
        events.append(sources._event(
            'SGC', feature['id'], p['utcTime'].replace(' ', 'T')+'Z', lat, lon, depth,
            p['mag'], p.get('magType'), p.get('place'), p.get('status'),
            f"https://www.sgc.gov.co/detallesismo/{feature['id']}/resumen"))
    for feature in json.loads((REPORT/'usgs_recent.txt').read_text())['features']:
        p = feature['properties']
        lon, lat, depth = feature['geometry']['coordinates']
        events.append(sources._event(
            'USGS', feature['id'], p['time']/1000, lat, lon, depth, p['mag'],
            p.get('magType'), p.get('place'), p.get('status'), p.get('url')))
    for feature in json.loads((REPORT/'emsc_recent.txt').read_text())['features']:
        p = feature['properties']
        eid = p.get('unid', feature.get('id'))
        events.append(sources._event(
            'EMSC', eid, p['time'], p['lat'], p['lon'], p.get('depth'), p.get('mag'),
            p.get('magtype'), p.get('flynn_region'), p.get('evtype'),
            f'https://www.seismicportal.eu/eventdetails.html?unid={eid}'))
    return events


def summarize():
    events = catalog_events()
    all_rows = []
    for file in sorted(REPORT.glob('*.json')):
        data = json.loads(file.read_text())
        if not isinstance(data, dict) or 'detections' not in data:
            continue
        for key, value in data['parameters'].items():
            setattr(config, key, value)
        rows = []
        for det in data['detections']:
            det['first_onset'] = UTCDateTime(det['first_onset'])
            candidates = [ev for ev in events if server.in_window(det, ev)]
            match = server.best_match(det, candidates)
            rows.append(dict(id=det['id'], level=det['level'],
                             delay=det['delay_from_reference_s'], stations=det['stations'],
                             match=match, discarded=det.get('discarded')))
        print(file.stem, 'coverage', sum('error' not in c for c in data['coverage'].values()),
              'triggers', len(data['triggers']), 'detections',
              [(r['level'], r['delay'], r['match']['id'] if r['match'] else None) for r in rows])
        all_rows.append(dict(case_profile=file.stem, detections=rows,
                             trigger_count=len(data['triggers'])))
    (REPORT/'comparison.json').write_text(
        json.dumps(all_rows, default=str, ensure_ascii=False, indent=2)+'\n')


def station_candidates():
    rows = []
    for line in (REPORT/'sgc_stations.txt').read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        fields = line.split('|')
        if fields[-1].strip() and UTCDateTime(fields[-1].strip()) < UTCDateTime('2026-09-29'):
            continue
        lat, lon = float(fields[4]), float(fields[5])
        distance = sources.distance_km(*config.MEDELLIN, lat, lon)
        rows.append((round(distance, 1), fields[1], fields[2], fields[3], lat, lon))
    (REPORT/'station-candidates.json').write_text(json.dumps(sorted(set(rows))[:20], indent=2)+'\n')


if __name__ == '__main__':
    summarize()
    station_candidates()
