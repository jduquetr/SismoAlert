import concurrent.futures
from copy import deepcopy
import io
import json
import queue
import time
import unittest
from unittest.mock import patch
import urllib.error

from obspy import UTCDateTime

import config
from detector import Associator
import server
import telegram


def detection(eid='DET1'):
    return {'id': eid, 'first_onset': UTCDateTime('2026-09-27T21:58:20'),
            'detected_at': UTCDateTime(), 'level': 'baja', 'message': 'HEL',
            'stations': {'HEL': {'onset': '2026-09-27T21:58:20', 'ratio': 12}}}


def event():
    return {'id': 'ev1', 'time': UTCDateTime(), 'lat': 6.2, 'lon': -75.5,
            'depth': 10, 'mag': 4.5, 'status': 'manual', 'place': 'Medellín',
            'url': 'https://example.org/', 'source': 'EMSC'}


class TelegramTests(unittest.TestCase):
    def setUp(self):
        telegram._sent.clear()
        self.messages = []
        self.sender = patch.object(telegram, 'send', side_effect=self.send)
        self.sender.start()
        self.addCleanup(self.sender.stop)

    def send(self, text, silent=False):
        self.messages.append((text, silent))
        return True

    def test_concurrent_first_confirmation_and_escalation(self):
        d = detection(); ev = dict(event(), priority='informativa')
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(lambda _: telegram.catalog(d, 'EMSC', ev), range(100)))
        self.assertEqual(len(self.messages), 1)
        telegram.detection(d)  # callback atrasado no borra la confirmación
        telegram.catalog(d, 'USGS', ev)
        telegram.catalog(d, 'SGC', dict(ev, priority='crítica'))
        self.assertEqual(len(self.messages), 2)
        self.assertFalse(self.messages[-1][1])

    def test_failed_enqueue_does_not_consume_transition(self):
        d = detection()
        with patch.object(telegram, 'send', return_value=False):
            telegram.detection(d)
        telegram.detection(d)
        self.assertEqual(len(self.messages), 1)
        ev = dict(event(), priority='crítica')
        with patch.object(telegram, 'send', return_value=False):
            telegram.catalog(d, 'EMSC', ev)
        telegram.catalog(d, 'EMSC', ev)
        self.assertEqual(len(self.messages), 2)

    def test_discard_suppresses_later_escalation(self):
        d = detection(); telegram.detection(d)
        d.update(discarded='artefacto', level='alta')
        telegram.discarded(d, 'artefacto')
        telegram.discarded(d, 'artefacto')
        telegram.level_change(d)
        telegram.catalog(d, 'EMSC', dict(event(), priority='crítica'))
        telegram.no_match(d)
        self.assertEqual(len(self.messages), 2)

    def test_catalog_outage_is_not_false_alarm(self):
        d = detection(); d['catalog_status'] = {'USGS': 'error', 'EMSC': 'ok'}
        telegram.no_match(d); telegram.no_match(d)
        self.assertEqual(len(self.messages), 1)
        self.assertIn('búsqueda incompleta', self.messages[0][0])
        self.assertNotIn('falsa alarma', self.messages[0][0])

    def test_bounded_state(self):
        for i in range(2100):
            telegram.detection(detection(str(i)))
        self.assertEqual(len(telegram._sent), 2048)

    def test_restore_does_not_reannounce_catalog(self):
        d=detection(); d['catalog']={'EMSC':dict(event(),priority='informativa')}
        telegram.restore([d])
        telegram.catalog(d,'EMSC',d['catalog']['EMSC'])
        self.assertEqual(self.messages, [])
        telegram.catalog(d,'EMSC',dict(d['catalog']['EMSC'], priority='crítica'))
        self.assertEqual(len(self.messages), 1)

    def test_health_checks_sample_age_even_when_packets_arrive(self):
        info=[{'station':'HEL','last_packet_age_s':1,'latency_s':700},
              {'station':'RUS','last_packet_age_s':1,'latency_s':5}]
        self.assertEqual(telegram._unhealthy(info), {'HEL'})

    def test_all_test_transitions_are_marked(self):
        d=detection(); d['test']=True; telegram.detection(d)
        d['level']='alta'; telegram.level_change(d); telegram.no_match(d)
        telegram.discarded(d,'prueba')
        self.assertEqual(len(self.messages), 4)
        self.assertTrue(all('PRUEBA' in m[0] for m in self.messages))

    def test_html_link_escaped(self):
        with patch.object(telegram, 'PAGE_URL', 'https://example.org/?a=1&b=<x>'):
            self.assertIn('&amp;b=&lt;x&gt;', telegram._link())


class WorkerTests(unittest.TestCase):
    def run_worker(self, errors, age=0):
        q = queue.Queue(); q.put(('hi', False, time.monotonic()-age))
        real_get = q.get
        # Stop after one work item, without starting a daemon.
        with patch.object(telegram, '_q', q), patch.object(q, 'get', side_effect=[real_get(), KeyboardInterrupt]), \
             patch.object(telegram, '_post', side_effect=errors) as post, \
             patch.object(telegram.time, 'sleep') as sleep:
            with self.assertRaises(KeyboardInterrupt):
                telegram._worker()
            self.assertEqual(q.unfinished_tasks, 0)
            return post.call_count, sleep.call_args_list

    def test_old_message_is_not_sent_after_outage(self):
        count, waits = self.run_worker([None], age=700)
        self.assertEqual((count, len(waits)), (0, 0))

    def test_429_honors_retry_after(self):
        err = urllib.error.HTTPError('secret-token-url', 429, '', {},
                                    io.BytesIO(b'{"parameters":{"retry_after":17}}'))
        count, waits = self.run_worker([err, None])
        self.assertEqual(count, 2)
        self.assertEqual(waits[0].args, (17.0,))

    def test_400_is_not_retried_or_logged_with_token(self):
        err = urllib.error.HTTPError('secret-token-url', 400, 'bad', {}, io.BytesIO())
        with self.assertLogs(telegram.log, level='WARNING') as logs:
            count, waits = self.run_worker([err])
        self.assertEqual((count, len(waits)), (1, 0))
        self.assertNotIn('secret-token', str(logs.output))


class ServerTests(unittest.TestCase):
    def setUp(self):
        server.hub = server.Hub(); server.active.clear(); server.assoc.current = None
        telegram._sent.clear()
        for target in ('server.store.save', 'server.threading.Thread', 'telegram.send'):
            p = patch(target, return_value=True) if target == 'telegram.send' else patch(target)
            mock = p.start(); self.addCleanup(p.stop)
            if target == 'server.threading.Thread': self.thread = mock
            if target == 'telegram.send': self.send = mock

    def test_registration_precedes_thread_and_duplicate_is_ignored(self):
        d = detection(); server.on_detection(d); server.on_detection(deepcopy(d))
        self.assertIs(server.active[d['id']], d)
        self.assertEqual(self.thread.call_count, 1)
        self.assertEqual(self.send.call_count, 1)

    def test_snapshot_is_detached(self):
        d = detection(); server.hub.upsert_detection(d, 'detection')
        d['stations']['RUS'] = {'onset': str(UTCDateTime()), 'ratio': 10}
        snap = server.hub.snapshot()
        self.assertNotIn('RUS', snap['detections'][0]['stations'])
        snap['detections'][0]['level'] = 'alta'
        self.assertEqual(server.hub.snapshot()['detections'][0]['level'], 'baja')

    def test_location_revision_recomputes_priority(self):
        d = detection(); ev = event(); server.attach(d, 'EMSC', ev)
        self.assertEqual(d['priority'], 'crítica')
        server.attach(d, 'EMSC', dict(ev, lat=12, lon=-80, depth=200))
        self.assertEqual(d['priority'], 'informativa')
        self.assertEqual(d['catalog']['EMSC']['depth'], 200)

    def test_emsc_fallback_attached_once_even_after_search(self):
        ev = event(); server.on_emsc_event(ev, 'create')
        eid = 'EMSC-' + ev['id']
        self.assertIn('EMSC', server.active[eid]['catalog'])
        self.assertEqual(self.send.call_count, 1)
        server.active.clear()
        server.on_emsc_event(ev, 'create')
        self.assertEqual(self.thread.call_count, 1)
        self.assertEqual(self.send.call_count, 1)

    def test_station_detection_enriches_existing_catalog_alert(self):
        ev = event(); server.on_emsc_event(ev, 'create')
        d = detection(); d['first_onset'] = ev['time'] + 2
        d['stations']['HEL']['onset'] = str(ev['time'] + 2)
        server.on_detection(d)
        self.assertEqual(len(server.hub.detections), 1)
        self.assertIn('HEL', server.assoc.current['stations'])
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(self.thread.call_count, 1)

    def test_emsc_update_can_be_first_relevant_version(self):
        server.on_emsc_event(event(), 'update')
        self.assertEqual(len(server.hub.detections), 1)

    def test_old_emsc_create_not_announced(self):
        server.on_emsc_event(dict(event(), time=UTCDateTime()-86400), 'create')
        self.send.assert_not_called()

    def test_search_finalizes_after_exception(self):
        d = detection(); server.on_detection(d)
        with patch.object(server, 'detection_window', side_effect=RuntimeError('bad')), \
             patch.object(server, 'catalog_sources', return_value=[('SGC', lambda *_: [])]):
            server.search_catalogs(d)
        self.assertEqual(d['search'], 'error')
        self.assertNotIn(d['id'], server.active)
        self.assertIn('búsqueda incompleta', self.send.call_args.args[0])

    def test_discarded_update_does_not_notify_again(self):
        d = detection(); d['discarded'] = 'artefacto'
        with patch.object(server, 'simultaneous_artifact', return_value='artefacto'):
            server.on_update(d)
        self.send.assert_not_called()

    def test_sgc_can_be_disabled(self):
        with patch.object(config, 'USE_SGC_BIWEEKLY', False):
            self.assertNotIn('SGC', dict(server.catalog_sources()))
            data = server.sgc_background(7)
            self.assertFalse(data['available'])
            self.assertIn('desactivado', data['reason'])


class AssociatorTests(unittest.TestCase):
    def test_peak_of_new_event_not_applied_to_previous_event(self):
        found = []
        a = Associator(lambda d: found.append(deepcopy(d)), lambda _: None)
        t = UTCDateTime('2026-09-27T00:00:00')
        a.trigger('HEL', t, 12)
        a.trigger('HEL', t+200, 5)
        a.peak('HEL', 12, t+200)
        self.assertEqual(len(found), 2)
        self.assertEqual(found[1]['first_onset'], t+200)

    def test_old_peak_cannot_raise_new_detection(self):
        a = Associator(lambda _: None, lambda _: None)
        t = UTCDateTime(); a.trigger('HEL', t, 12)
        a.peak('HEL', 25, t-20)
        self.assertEqual(a.current['stations']['HEL']['ratio'], 12)


class MultiChatTests(unittest.TestCase):
    def test_each_chat_gets_its_own_queue_item(self):
        q = queue.Queue()
        with patch.object(telegram, '_q', q), patch.object(telegram, 'TOKEN', 't'), \
             patch.object(telegram, 'CHAT_IDS', ['111', '-100222']):
            self.assertTrue(telegram.send('hola', silent=True))
        items = [q.get_nowait() for _ in range(q.qsize())]
        self.assertEqual([i[3] for i in items], ['111', '-100222'])
        self.assertTrue(all(i[0] == 'hola' and i[1] is True for i in items))


if __name__ == '__main__':
    unittest.main()
