"""Frontend contract; all database fixtures are temporary and isolated."""
import hashlib
import unittest
from unittest.mock import patch

import test_dashboard_v2 as legacy


class ContaminantsFrontendTests(unittest.TestCase):
    def setUp(self):
        legacy.DashboardV2Tests.setUp(self)

    def tearDown(self):
        legacy.DashboardV2Tests.tearDown(self)

    def test_lab_has_distinct_controls_and_unambiguous_model_label(self):
        html = self.client.get('/inicio/explorar').get_data(as_text=True)
        for item in ('id="pollutantWorkspace" hidden', 'id="pollutantSource"',
                     'id="pollutantStation"', 'id="pollutantVariable"',
                     'id="pollutantFrom"', 'id="pollutantTo"',
                     'id="pollutantRows"', 'gases-v1',
                     'id="airWorkspace"', 'id="weatherWorkspace"'):
            self.assertIn(item, html)
        self.assertIn('no convierte una hora', html.lower())
        for name in ('contaminants.js', 'contaminants.css'):
            self.assertIn(name, html)
        self.assertNotIn('src="https://', html)

    def test_frontend_assets_do_not_enable_a_scientific_write_path(self):
        with self.client.get('/static/v2/js/contaminants.js') as response:
            self.assertEqual(response.status_code, 200)
            js = response.get_data(as_text=True)
        for text in ('Modelo, no medición', 'openaq-archivo', 'open-meteo-cams',
                     'resolucion=hora', 'incluir_marcadas=1', 'spanGaps: false',
                     "'/observaciones?'", "'/cobertura?'", 'AbortController'):
            self.assertIn(text, js)
        for verb in ('POST', 'PUT', 'DELETE'):
            self.assertNotIn('method: ' + repr(verb), js)

    def test_old_routes_remain_read_only(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        for route in ('/', '/v2', '/v2/datos', '/inicio', '/inicio/explorar'):
            self.assertEqual(self.client.get(route).status_code, 200)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)

    def test_missing_dataset_does_not_invent_a_series(self):
        with patch('app.DB', self.db.parent / 'missing.db'):
            response = self.client.get('/inicio/explorar')
        self.assertEqual(response.status_code, 503)
        html = response.get_data(as_text=True)
        self.assertIn('id="pollutantCount">—', html)
        self.assertIn('id="pollutantSource" disabled', html)
        self.assertNotIn(str(self.db.parent), html)


if __name__ == '__main__':
    unittest.main()
