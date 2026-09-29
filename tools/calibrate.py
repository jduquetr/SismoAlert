"""Reproduce la comparación del PR usando replay.py y las ondas cacheadas.

.venv/bin/python tools/calibrate.py --offline
Sin --offline descarga solicitudes que no estén en datos/replay/.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from obspy import UTCDateTime
import config
import replay

TUNING = [
    ('istmina', '2026-09-27T21:57:51', 10, 5),
    ('chaparral', '2026-09-26T06:38:16', 3, 5),
    ('santos', '2026-09-28T14:42:32', 3, 5),
    ('istmina2', '2026-09-25T00:57:05', 3, 5),
    ('control1', '2026-09-27T10:00:00', 3, 12),
    ('control2', '2026-09-28T18:00:00', 3, 12),
]
VALIDATION = [
    ('holdout-chaparral', '2026-09-28T08:39:54', 3, 5),
    ('holdout-istmina', '2026-09-24T07:39:04', 3, 5),
    ('holdout-istmina2', '2026-09-27T03:15:38', 3, 5),
    ('background-hour', '2026-09-28T02:00:00', 3, 57),
]
BASE = dict(THR_ON=5., THR_OFF=1.5, STA_S=1., LTA_S=30., MIN_RATIO=8.,
            LOCAL_ONLY_MIN_RATIO=8., MIN_STATIONS=2, MIN_STATIONS_REMOTE=3,
            ASSOC_WINDOW_S=120, DEAD_TIME_S=30)
PROFILES = {
    'base': {},
    'ratio6': dict(MIN_RATIO=6., LOCAL_ONLY_MIN_RATIO=6.),
    'ratio10': dict(MIN_RATIO=10., LOCAL_ONLY_MIN_RATIO=10.),
    'on4': dict(THR_ON=4.),
    'on6': dict(THR_ON=6.),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--output-dir', type=Path, default=ROOT/'reports/revision-2026-09-29')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for case in TUNING + VALIDATION:
        name, origin, before, after = case
        t0 = UTCDateTime(origin); start, end = t0-before*60, t0+after*60
        st, coverage = replay.download(start, end, ROOT/'datos/replay', args.offline)
        if not st:
            raise RuntimeError(f'{name}: ninguna estación disponible')
        profiles = PROFILES if case in TUNING else {k: PROFILES[k] for k in ('base', 'ratio10')}
        for profile, overrides in profiles.items():
            parameters = BASE | overrides
            for key, value in parameters.items():
                setattr(config, key, value)
            result = replay.simulate(st, start, end, t0)
            result.update(reference=str(t0), start=str(start), end=str(end),
                          parameters=parameters, coverage=coverage)
            (args.output_dir/f'{name}-{profile}.json').write_text(
                json.dumps(result, default=str, ensure_ascii=False, indent=2)+'\n')
            print(name, profile, len(result['triggers']), len(result['detections']), flush=True)


if __name__ == '__main__':
    main()
