"""AERIS 3.0: la experiencia inmersiva es opcional, local, accesible y no altera los datos."""
import json
import re
import unittest
from pathlib import Path

import test_dashboard_v2 as legacy

RAIZ = Path(__file__).resolve().parents[1]


class InmersivoTests(unittest.TestCase):
    def setUp(self):
        legacy.DashboardV2Tests.setUp(self)

    def tearDown(self):
        legacy.DashboardV2Tests.tearDown(self)

    def texto(self, ruta, **kw):
        r = self.client.get(ruta, **kw)
        self.assertEqual(r.status_code, 200)
        return r, r.get_data(as_text=True)

    def test_predeterminada_inmersiva_y_clasica_disponible(self):
        r, html = self.texto('/inicio')
        self.assertIn('escena-intro', html)
        self.assertIn('href="/inicio?experiencia=clasica"', html)
        self.assertIsNone(r.headers.get('Set-Cookie'))
        _, clasica = self.texto('/inicio?experiencia=clasica')
        self.assertNotIn('escena-intro', clasica)
        self.assertNotIn('gsap', clasica)
        self.assertIn('El aire que respiras', clasica)

    def test_inmersiva_por_parametro_y_galleta_segura(self):
        r, html = self.texto('/inicio?experiencia=inmersiva')
        galleta = r.headers['Set-Cookie']
        for atributo in ('aeris_experiencia=inmersiva', 'HttpOnly', 'SameSite=Lax', 'Path=/inicio'):
            self.assertIn(atributo, galleta)
        self.assertIn('class="exp-inmersiva escena-sin-js"', html)
        self.assertIn('id="atmosfera"', html)
        self.assertEqual(html.count('<h1'), 1)
        for control in ('id="saltarEscena"', 'id="motionToggle"', 'href="#estado"', 'href="/inicio/explorar"'):
            self.assertIn(control, html)
        # La galleta recuerda la elección y la clásica sigue disponible.
        _, recordada = self.texto('/inicio')
        self.assertIn('escena-intro', recordada)
        _, clasica = self.texto('/inicio?experiencia=clasica')
        self.assertNotIn('escena-intro', clasica)

    def test_valor_desconocido_se_ignora(self):
        r, html = self.texto('/inicio?experiencia=<script>')
        self.assertIn('escena-intro', html)  # se usa la predeterminada
        self.assertNotIn('<script>"', html)
        self.assertIsNone(r.headers.get('Set-Cookie'))

    def test_solo_recursos_locales_y_verificados(self):
        _, html = self.texto('/inicio?experiencia=inmersiva')
        self.assertNotRegex(html, r'<(script|link)[^>]+(src|href)="https?://')
        for ruta in re.findall(r'(?:src|href)="(/static/[^"]+)"', html):
            self.assertEqual(self.client.get(ruta).status_code, 200, ruta)
        manifiesto = json.loads((RAIZ / 'static/v2/vendor/manifest.json').read_text(encoding='utf-8'))
        versiones = {m['package']: m['version'] for m in manifiesto}
        self.assertEqual(versiones['gsap'], '3.15.0')
        self.assertIn('@fontsource/instrument-serif', versiones)
        self.assertIn('@fontsource-variable/inter', versiones)

    def test_particulas_y_cifras_provienen_de_los_datos(self):
        _, html = self.texto('/inicio?experiencia=inmersiva')
        self.assertRegex(html, r'data-particulas="\d+"')
        # Cada cifra animada termina en el valor publicado que ya está en el HTML.
        for final, visible in re.findall(r'data-cifra="(\d+)">([\d,]+)<', html):
            self.assertEqual(int(final), int(visible.replace(',', '')))

    def test_respaldo_y_movimiento_reducido_en_el_codigo(self):
        atm = (RAIZ / 'static/v2/js/escena/atmosfera.js').read_text(encoding='utf-8')
        nar = (RAIZ / 'static/v2/js/escena/narrativa.js').read_text(encoding='utf-8')
        css = (RAIZ / 'static/v2/css/inmersivo.css').read_text(encoding='utf-8')
        self.assertIn('prefers-reduced-motion', atm)
        self.assertIn('webglcontextlost', atm)
        self.assertIn('visibilitychange', atm)
        self.assertIn('prefers-reduced-motion', nar)
        self.assertIn('.atmosfera-estatica .escena-respaldo', css)
        self.assertIn('@media(prefers-reduced-motion:reduce)', css)


if __name__ == '__main__':
    unittest.main()
