"""Six-pollutant educational contract; observations remain isolated test fixtures."""
import hashlib
import json
import re
import unittest
from unittest.mock import patch

import test_dashboard_v2 as legacy
from aeris_web.aprende import configuracion_simulador


class AprendeMultiTests(unittest.TestCase):
    def setUp(self):
        legacy.DashboardV2Tests.setUp(self)

    def tearDown(self):
        legacy.DashboardV2Tests.tearDown(self)

    def test_published_reference_units_precision_and_methods(self):
        # Independent constants from NOM-172 Tables 2–9, reference January 2026.
        expected = {
            'pm25': ('µg/m³', 0, [15, 25, 79, 130], 'promedio 24 h'),
            'pm10': ('µg/m³', 0, [45, 50, 132, 213], 'promedio 24 h'),
            'o3': ('ppm', 3, [.058, .090, .135, .175], 'máximo horario'),
            'no2': ('ppm', 3, [.053, .106, .160, .213], 'máximo horario'),
            'so2': ('ppm', 3, [.035, .075, .185, .304], 'máximo horario'),
            'co': ('ppm', 2, [5, 9, 12, 16], 'máximo móvil 8 h'),
        }
        response = self.client.get('/inicio/aprende')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        data = json.loads(re.search(r'id="apContaminantes" type="application/json">(.*?)</script>', html, re.S)[1])
        self.assertEqual(set(data), set(expected))
        for key, (unit, decimals, limits, method) in expected.items():
            config = data[key]
            self.assertEqual((config['unidad'], config['decimales'], config['metodo']), (unit, decimals, method))
            self.assertEqual([b['tope'] for b in config['bandas']], limits + [None])
            self.assertTrue(config['explicacion'])
            self.assertIn(f'value="{key}"', html)
        self.assertIn('SIMULADOR EDUCATIVO', html)
        self.assertIn('Un día real de PM2.5', html)

    def test_configuration_does_not_copy_thresholds_into_javascript(self):
        # Changing the source contract in memory must reach the page without editing JS.
        config = configuracion_simulador()
        config['pm10']['metodo'] = 'method-contract-test'
        with patch('aeris_web.aprende.configuracion_simulador', return_value=config):
            html = self.client.get('/inicio/aprende').get_data(as_text=True)
        self.assertIn('method-contract-test', html)

    def test_learning_and_home_preserve_database_and_original_routes(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        for path in ('/', '/v2', '/v2/datos', '/inicio', '/inicio/aprende'):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)
        html = self.client.get('/inicio').get_data(as_text=True)
        for text in ('gases-v1', 'desde 2021', 'solo a PM2.5', 'Open-Meteo CAMS · no integrado'):
            self.assertIn(text, html)

    def test_no_real_examples_never_invents_an_observation(self):
        with patch('aeris_web.aprende.registros_diarios', return_value=[]), patch('aeris_web.aprende.read_estado', return_value=None):
            html = self.client.get('/inicio/aprende').get_data(as_text=True)
        self.assertIn('No hay ejemplos reales disponibles', html)
        self.assertNotIn('id="apEjemplos"', html)
        self.assertIn('id="apEntrada"', html)  # Educational controls still work.
        self.assertIn('El valor elegido no es una medición', html)

    def test_precision_of_real_hours_is_not_lost_before_averaging(self):
        from aeris_web.aprende import horas_del_dia
        from contextlib import closing
        from datetime import date
        import sqlite3
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1352686,'2021-09-23T10:00:00Z','pm25',15.4949,'µg/m³')")
        hours = horas_del_dia(self.db, 'OpenAQ', 1352686, date(2021, 9, 23))
        self.assertEqual(next(h['valor'] for h in hours if h['valor'] is not None), 15.4949)


if __name__ == '__main__':
    unittest.main()
