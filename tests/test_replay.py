import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np
from obspy import Stream, Trace, UTCDateTime
import config
from detector import StationTrigger
import replay


class ReplayTests(unittest.TestCase):
    def test_gap_resets_instead_of_inventing_signal(self):
        t = UTCDateTime('2026-09-27')
        def trace(at):
            return Trace(np.zeros(4000), header={'station':'HEL', 'network':'CM',
                         'location':'00','channel':'HHZ','sampling_rate':100,'starttime':at})
        st = Stream([trace(t), trace(t+60)])
        trig = StationTrigger('HEL'); trig.add(st[0])
        with patch.object(trig, 'reset', wraps=trig.reset) as reset:
            trig.add(st[1]); reset.assert_called_once()
        self.assertEqual(trig.stream[0].stats.starttime, t+60)
        with patch.object(config, 'STATIONS', {'HEL': config.STATIONS['HEL']}):
            result = replay.simulate(st, t, t+100, t+50)
        self.assertEqual(result['triggers'], [])

    def test_offline_missing_is_reported_not_downloaded(self):
        t=UTCDateTime()
        with TemporaryDirectory() as tmp, patch.object(config, 'STATIONS', {'HEL': config.STATIONS['HEL']}), \
             patch.object(replay, 'Client') as client:
            st, coverage = replay.download(t, t+60, Path(tmp), offline=True)
        client.assert_not_called()
        self.assertEqual(len(st), 0)
        self.assertEqual(coverage['HEL']['error'], 'FileNotFoundError')
