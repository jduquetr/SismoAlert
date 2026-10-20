import unittest
from unittest.mock import patch
import copia_estatica


class SnapshotUiTests(unittest.TestCase):
    @patch.object(copia_estatica, "basemap", return_value='{"type":"FeatureCollection","features":[]}')
    @patch.object(copia_estatica, "cached", return_value='/* leaflet */')
    def test_snapshot_escapes_script_and_uses_shared_ui(self, *_):
        state = {"stations": [], "detections": [], "log": [{"text": "</script><script>alert(1)</script>"}]}
        html = copia_estatica.build(state)
        self.assertIn('const SNAPSHOT = ', html)
        self.assertIn('const SGC_SNAPSHOT = null;', html)
        self.assertNotIn('</script><script>alert(1)</script>', html)
        self.assertIn('\\u003c/script>', html)
        self.assertIn('if (isSnapshot)', html)
        self.assertNotIn('fetch("/test', html)


if __name__ == '__main__':
    unittest.main()
