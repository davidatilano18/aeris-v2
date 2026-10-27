"""Isolated protocol fixtures, never observations served by the real dashboard."""
import hashlib
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

import test_dashboard_v2 as legacy
from aeris_web.home import read_home


class HomeTests(unittest.TestCase):
    def setUp(self):
        legacy.DashboardV2Tests.setUp(self)

    def tearDown(self):
        legacy.DashboardV2Tests.tearDown(self)

    def test_preserves_original_routes_and_adds_home(self):
        for route in ('/', '/v2', '/v2/datos', '/inicio'):
            self.assertEqual(self.client.get(route).status_code, 200)
        # La portada clásica sigue disponible; la inmersiva (3.0) es la predeterminada.
        text = self.client.get('/inicio?experiencia=clasica').get_data(as_text=True)
        self.assertIn('El aire que respiras', text)
        self.assertIn('EVIDENCIA INSUFICIENTE', text)
        self.assertIn('deshabilitados', text)
        self.assertIn('/v2/vendor/leaflet/leaflet.js', text)
        self.assertNotIn('<script src="https://', text)

    def test_source_separation_no_state_mean_and_read_only(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        result = read_home(self.db, legacy.NOW)
        self.assertEqual(result['total'], 7)
        self.assertEqual(result['observed_stations'], 2)
        self.assertEqual([s['count'] for s in result['sources']], [5, 2])
        self.assertNotIn('mean', result)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)

    def test_historical_marques_not_fresh_and_zero_preserved(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1352686,'2021-09-23T10:00:00Z','pm25',0,'µg/m³')")
        result = read_home(self.db, legacy.NOW)
        self.assertEqual(result['marques']['records'], 1)
        self.assertFalse(result['marques']['fresh'])
        self.assertEqual(result['marques']['sources'][0]['months'], ['2021-09'])

    def test_empty_database_and_catalog_without_observations(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('DELETE FROM calidad_mediciones')
            conn.execute('DELETE FROM mediciones')
        result = read_home(self.db, legacy.NOW)
        self.assertEqual(result['total'], 0)
        self.assertEqual(result['observed_municipalities'], 0)
        self.assertIsNone(result['latest'])
        self.assertGreater(result['catalog_stations'], 0)
        text = self.client.get('/inicio').get_data(as_text=True)
        self.assertIn('Todavía no hay mediciones visibles', text)
        self.assertIn('No hay observaciones locales disponibles', text)

    def test_unavailable_database_has_explicit_error_without_path(self):
        with patch('app.DB', self.db.parent/'missing.db'):
            response = self.client.get('/inicio')
        self.assertEqual(response.status_code, 503)
        text = response.get_data(as_text=True)
        self.assertIn('No pudimos consultar', text)
        self.assertNotIn(str(self.db.parent), text)

    def test_invalid_unit_fails_closed_and_future_not_counted(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1352686,'2099-01-01T00:00:00Z','pm25',10,'µg/m³')")
        self.assertEqual(read_home(self.db, legacy.NOW)['total'], 7)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE mediciones SET unidad='ppm' WHERE sensor_id=?", (legacy.SID,))
        with self.assertRaises(RuntimeError):
            read_home(self.db, legacy.NOW)

    def test_local_assets_and_accessible_motion_contract(self):
        for file in ('css/home.css', 'js/home.js'):
            with self.client.get('/static/v2/'+file) as response:
                self.assertEqual(response.status_code, 200)
                text = response.get_data(as_text=True)
                self.assertIn('prefers-reduced-motion', text)
        text = self.client.get('/inicio').get_data(as_text=True)
        self.assertIn('Saltar al contenido', text)
        # La lista de estaciones queda visible (no en un desplegable) y cada una enfoca el mapa.
        self.assertIn('aria-label="Estaciones de calidad del aire"', text)
        self.assertIn('class="station-focus"', text)
        self.assertIn('data-vista="metro"', text)

    def test_clock_must_be_zoned(self):
        with self.assertRaises(ValueError):
            read_home(self.db, legacy.NOW.replace(tzinfo=None))

    def test_visual_previous_version_is_available_with_preserved_assets(self):
        response = self.client.get('/inicio/anterior')
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn('home_v1.css', text)
        self.assertIn('home_v1.js', text)
        self.assertIn('orbital', text)
        for asset in ('css/home_v1.css', 'js/home_v1.js'):
            with self.client.get('/static/v2/'+asset) as value:
                self.assertEqual(value.status_code, 200)

    def test_new_home_has_real_telemetry_and_accessible_station_chart(self):
        text = self.client.get('/inicio?experiencia=clasica').get_data(as_text=True)
        self.assertIn('REGISTROS PARA EXPLORAR', text)
        self.assertIn('/inicio/anterior', text)
        self.assertIn('id="homeChart"', text)
        self.assertIn('aria-describedby="historySummary"', text)
        self.assertIn('id="historyRows"', text)
        self.assertIn('home_history.js', text)
        self.assertNotIn('class="orbital"', text)

    def test_history_script_uses_existing_endpoint_without_imputation(self):
        with self.client.get('/static/v2/js/home_history.js') as response:
            text = response.get_data(as_text=True)
        for contract in ('/api/v2/observations?', 'spanGaps:false', 'tension:0',
                         'animation:false', 'AbortController', 'period:', 'aria-busy'):
            self.assertIn(contract, text)

    def test_reverted_batch_does_not_appear_in_home(self):
        import importlib
        module = importlib.import_module('test_batch_visibility')
        fixture = module.BatchVisibilityTests('test_active_reverted_and_reactivated_states')
        fixture.setUp()
        try:
            fixture.activate()
            self.assertEqual(read_home(fixture.db, legacy.NOW)['total'], 74)
            fixture.revert()
            self.assertEqual(read_home(fixture.db, legacy.NOW)['total'], 3)
            self.assertEqual(fixture.count(physical=True), 74)
        finally:
            fixture.tearDown()
