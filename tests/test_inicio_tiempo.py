"""Sección meteorológica del inicio: separa observación y modelo y no rompe PM2.5."""
import unittest

import test_dashboard_v2 as legacy


class InicioTiempoTests(unittest.TestCase):
    def setUp(self):
        legacy.DashboardV2Tests.setUp(self)

    def tearDown(self):
        legacy.DashboardV2Tests.tearDown(self)

    def test_seccion_tiempo_y_recursos_locales(self):
        text = self.client.get('/inicio').get_data(as_text=True)
        self.assertIn('id="tiempo"', text)
        self.assertIn('v2/js/home_tiempo.js', text)
        self.assertIn('no una calibración ni una validación del modelo', text)
        self.assertIn('NASA POWER', text)
        self.assertNotIn('<script src="https://', text)
        # PM2.5 sigue en su propia sección.
        self.assertIn('id="historyChartBox"', text)

    def test_favicon_local(self):
        response = self.client.get('/favicon.ico')
        self.assertEqual((response.status_code, response.mimetype), (200, 'image/png'))
        response.close()

    def test_sin_capa_ambiental_la_api_responde_503_y_el_inicio_200(self):
        # La base de prueba legada no tiene tablas amb_*: el inicio no debe fallar.
        self.assertEqual(self.client.get('/inicio').status_code, 200)
        self.assertEqual(self.client.get('/api/ambiental/v1/estaciones').status_code, 503)


if __name__ == '__main__':
    unittest.main()
