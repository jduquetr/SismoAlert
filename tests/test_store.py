import unittest
from unittest.mock import patch
from obspy import UTCDateTime
import store


class StoreTests(unittest.TestCase):
    def test_daily_count_uses_all_records_and_excludes_tests_and_discarded(self):
        now = str(UTCDateTime())
        records = {str(i): {'properties': {'deteccion': {'detected_at':now}}} for i in range(45)}
        records['1']['properties']['deteccion']['discarded']='noise'
        records['2']['properties']['deteccion']['test']=True
        records['3']['properties']['deteccion']['detected_at']=str(UTCDateTime()-90000)
        with patch.object(store,'_records',records):
            self.assertEqual(store.count_recent(86400),42)
