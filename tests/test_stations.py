"""Las señales regionales se pueden observar sin modificar las alertas calibradas."""
import unittest
from unittest.mock import Mock, patch

import numpy as np
from obspy import Trace, UTCDateTime

import config
import server
import telegram
from station_monitor import StationMonitor


def trace(station='TULM', end=None):
    net, loc, cha, *_ = config.ALL_STATIONS[station]
    end = UTCDateTime() if end is None else UTCDateTime(end)
    return Trace(np.ones(100, dtype=np.int32), header=dict(
        station=station, network=net, location=loc, channel=cha,
        sampling_rate=100, starttime=end - 0.99))


class ObservationTests(unittest.TestCase):
    def test_freshness_distinguishes_packet_arrival_from_sample_time(self):
        monitor = StationMonitor('TULM')
        self.assertIsNone(monitor.status()['latency_s'])
        with patch('station_monitor.time.time', return_value=1000):
            monitor.add(trace(end=200))
            self.assertEqual(monitor.status()['last_packet_age_s'], 0)
            self.assertEqual(monitor.status()['latency_s'], 800)
        with patch('station_monitor.time.time', return_value=1100):
            self.assertEqual(monitor.status()['last_packet_age_s'], 100)
            self.assertEqual(monitor.status()['latency_s'], 900)

    def test_out_of_order_and_empty_records_do_not_replace_latest_sample(self):
        monitor = StationMonitor('TULM')
        with patch('station_monitor.time.time', return_value=1000):
            monitor.add(trace(end=990))
            monitor.add(trace(end=900))
            empty = trace(end=1000); empty.data = np.array([], dtype=np.int32)
            monitor.add(empty)
            self.assertEqual(monitor.status()['latency_s'], 10)

    def test_all_observation_streams_bypass_detector_and_associator(self):
        monitors = {s: StationMonitor(s) for s in config.OBSERVATION_STATIONS}
        with patch.object(server, 'observations', monitors), \
             patch.object(server, 'assoc') as assoc, patch.object(telegram, 'send') as send:
            for sta in monitors:
                # Even a large amplitude pulse must only update reception status.
                tr = trace(sta); tr.data[50:] = 100000000
                server.on_trace(tr)
                self.assertLess(monitors[sta].status()['last_packet_age_s'], 1)
                self.assertFalse(monitors[sta].status()['triggered'])
            self.assertEqual(assoc.mock_calls, [])
            send.assert_not_called()
        self.assertTrue(set(monitors).isdisjoint(server.triggers))

    def test_wrong_network_location_or_channel_is_not_counted(self):
        for sta in ('TULM', 'HEL'):
            for field, value in (('network', 'XX'), ('location', '99'), ('channel', 'HHN')):
                with self.subTest(station=sta, field=field):
                    tr = trace(sta); setattr(tr.stats, field, value)
                    target = Mock()
                    with patch.object(server, 'observations', {'TULM': target}), \
                         patch.object(server, 'triggers', {'HEL': target}):
                        server.on_trace(tr)
                    target.add.assert_not_called()

    def test_calibrated_station_still_reaches_associator(self):
        onset = UTCDateTime()
        detector = Mock(peak_ratio=12)
        detector.add.return_value = onset
        with patch.object(server, 'triggers', {'HEL': detector}), patch.object(server, 'assoc') as assoc:
            server.on_trace(trace('HEL'))
            assoc.trigger.assert_called_once_with('HEL', onset, 12)

    def test_live_observations_cannot_mask_loss_of_all_detector_stations(self):
        info = [dict(station=s, alerts_enabled=True, last_packet_age_s=None, latency_s=None)
                for s in config.STATIONS]
        info += [dict(station=s, alerts_enabled=False, last_packet_age_s=1, latency_s=1)
                 for s in config.OBSERVATION_STATIONS]
        with patch.object(server, 'station_info', return_value=info):
            health = server.detector_station_info()
        self.assertEqual(len(health), len(config.STATIONS))
        self.assertEqual(telegram._unhealthy(health), set(config.STATIONS))

    def test_public_state_describes_roles_and_missing_signal(self):
        monitors = {s: StationMonitor(s) for s in config.OBSERVATION_STATIONS}
        with patch.object(server, 'observations', monitors):
            info = server.station_info()
        self.assertEqual({s['station'] for s in info}, set(config.ALL_STATIONS))
        for station in info:
            self.assertEqual(station['alerts_enabled'], station['station'] in config.STATIONS)
            if not station['alerts_enabled']:
                self.assertIsNone(station['latency_s'])
                self.assertFalse(station['triggered'])

    def test_one_seedlink_connection_requests_exact_configured_channels(self):
        with patch.object(server, 'SeedLinkClient') as client, patch.object(server.hub, 'note'):
            client.return_value.run.side_effect = KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):
                server.seedlink_loop()
        client.assert_called_once()
        channels = client.call_args.args[1]
        expected = {(net, sta, loc + cha) for sta, (net, loc, cha, *_) in config.ALL_STATIONS.items()}
        self.assertEqual(set(channels), expected)
        self.assertEqual(len(channels), len(expected))


if __name__ == '__main__':
    unittest.main()
