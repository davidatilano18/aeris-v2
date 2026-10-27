"""Frontend regression fixtures are isolated from the production database."""
import hashlib
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

import test_dashboard_v2 as legacy
from aeris_web.home import read_home


class HomeMethodTests(unittest.TestCase):
    def setUp(self):
        legacy.DashboardV2Tests.setUp(self)

    def tearDown(self):
        legacy.DashboardV2Tests.tearDown(self)

    def test_methods_available_in_both_experiences_without_writes(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        for mode in ('clasica', 'inmersiva'):
            page = self.client.get('/inicio?experiencia=' + mode).get_data(as_text=True)
            for text in ('Cómo trabajamos', 'Brecha de monitoreo en El Marqués',
                         'NOM-172-SEMARNAT-2023', '18 horas', 'NASA POWER',
                         '/inicio/datos/pm25-diario.csv', 'home_method.js', 'home_method.css'):
                self.assertIn(text, page)
            self.assertIn('no confirma un error', page)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)

    def test_historical_map_list_has_real_date_and_no_recent_claim(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1352686,'2021-09-23T10:00:00Z','pm25',0,'µg/m³')")
        overview = read_home(self.db, legacy.NOW)
        with patch('aeris_web.home.read_home', return_value=overview):
            page = self.client.get('/inicio').get_data(as_text=True)
        self.assertIn('Solo historial', page)
        self.assertIn('23/09/2021', page)
        self.assertIn('Datos recientes · hasta 2 h', page)
        self.assertIn('Catálogo sin registros locales', page)
        self.assertFalse(overview['marques']['fresh'])

    def test_missing_database_does_not_invent_quality_counts(self):
        with patch('app.DB', self.db.parent / 'missing.db'):
            response = self.client.get('/inicio')
            export = self.client.get('/inicio/datos/pm25-diario.csv')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(export.status_code, 503)
        self.assertIn('id="methodDays">—', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
