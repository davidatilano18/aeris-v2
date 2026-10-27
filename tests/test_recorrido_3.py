"""El recorrido de AERIS 3.0 no lleva a las vistas anteriores salvo de forma explícita."""
import re
import unittest
from pathlib import Path

import test_dashboard_v2 as legacy

RAIZ = Path(__file__).resolve().parents[1]


class RecorridoTests(unittest.TestCase):
    def setUp(self):
        legacy.DashboardV2Tests.setUp(self)

    def tearDown(self):
        legacy.DashboardV2Tests.tearDown(self)

    def test_paginas_3_sin_enlaces_a_v2(self):
        for ruta in ('/inicio', '/inicio?experiencia=clasica', '/inicio/explorar', '/inicio/aprende'):
            html = self.client.get(ruta).get_data(as_text=True)
            self.assertNotRegex(html, r'href="/v2', ruta)
        datos = self.client.get('/inicio/datos').get_data(as_text=True)
        self.assertEqual(re.findall(r'href="(/v2[^"]*)"', datos), ['/v2/datos'])  # «versión anterior», explícito
        for js in ('home.js', 'home_history.js', 'workspace.js'):
            self.assertNotIn("'/v2", (RAIZ / 'static/v2/js' / js).read_text(encoding='utf-8'), js)

    def test_comparacion_por_enlace_directo(self):
        html = self.client.get('/inicio').get_data(as_text=True)
        self.assertIn('href="/inicio/explorar#comparacion"', html)
        self.assertIn("location.hash!=='#comparacion'", (RAIZ / 'static/v2/js/workspace.js').read_text(encoding='utf-8'))

    def test_vistas_anteriores_ofrecen_volver(self):
        for ruta in ('/v2', '/v2/datos'):
            html = self.client.get(ruta).get_data(as_text=True)
            self.assertIn('class="aviso-version"', html, ruta)
            self.assertIn('href="/inicio"', html)


if __name__ == '__main__':
    unittest.main()
