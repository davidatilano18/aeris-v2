"""Datos abiertos (CSV) y Aprende: fieles a la base, de solo lectura y coherentes con las reglas."""
import csv
import hashlib
import io
import json
import re
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path

import test_dashboard_v2 as legacy
from aeris_web.datos_abiertos import CONJUNTOS
from aeris_web.estado import LIMITES, OMS_24H
from aeris_web.indice import CONTAMINANTES

RAIZ = Path(__file__).resolve().parents[1]


class DatosAprendeTests(unittest.TestCase):
    def setUp(self):
        legacy.DashboardV2Tests.setUp(self)

    def tearDown(self):
        legacy.DashboardV2Tests.tearDown(self)

    def csv(self, nombre):
        r = self.client.get(f'/inicio/datos/{nombre}.csv')
        self.assertEqual(r.status_code, 200)
        texto = r.get_data(as_text=True)
        self.assertTrue(texto.startswith('\ufeff'))
        self.assertIn(f'aeris_{nombre}_', r.headers['Content-Disposition'])
        self.assertTrue(r.mimetype == 'text/csv')
        return list(csv.reader(io.StringIO(texto.lstrip('\ufeff'))))

    def test_pm25_horario_completo_y_base_intacta(self):
        antes = hashlib.sha256(self.db.read_bytes()).hexdigest()
        filas = self.csv('pm25-horario')
        self.assertEqual(filas[0], [c for c, _ in CONJUNTOS['pm25-horario']['columnas']])
        with closing(sqlite3.connect(self.db)) as conn:
            total = conn.execute("SELECT COUNT(*) FROM mediciones WHERE contaminante='pm25'").fetchone()[0]
        self.assertEqual(len(filas) - 1, total)
        for fila in filas[1:]:
            self.assertRegex(fila[6], r'Z$')            # fecha_utc
            self.assertRegex(fila[7], r'[+-]\d\d:\d\d$')  # fecha_local con desfase
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), antes)

    def test_pm25_diario_columnas_y_clasificaciones_validas(self):
        filas = self.csv('pm25-diario')
        self.assertEqual(filas[0], [c for c, _ in CONJUNTOS['pm25-diario']['columnas']])
        validas = {'Buena', 'Aceptable', 'Mala', 'Muy mala', 'Extremadamente mala', 'Sin promedio', 'En revisión'}
        for fila in filas[1:]:
            self.assertIn(fila[8], validas)
            if fila[8] in ('Sin promedio', 'En revisión'):
                self.assertEqual(fila[7], '')

    def test_errores_y_solo_lectura(self):
        self.assertEqual(self.client.get('/inicio/datos/inexistente.csv').status_code, 404)
        # La base de prueba no tiene capa ambiental: sin datos no se inventa un archivo.
        self.assertEqual(self.client.get('/inicio/datos/meteorologia-mmqt.csv').status_code, 404)
        self.assertEqual(self.client.post('/inicio/datos/pm25-horario.csv').status_code, 405)

    def test_pagina_datos_y_enlaces(self):
        html = self.client.get('/inicio/datos').get_data(as_text=True)
        for clave in CONJUNTOS:
            self.assertIn(f'id="{clave}"', html)
        self.assertIn('href="/inicio/datos/pm25-horario.csv"', html)
        self.assertIn('no está disponible', html)  # conjuntos ambientales ausentes en la base de prueba
        inicio = self.client.get('/inicio').get_data(as_text=True)
        self.assertIn('<a href="/inicio/datos">Datos</a>', inicio)
        self.assertIn('href="/inicio/aprende"', inicio)

    def test_aprende_y_limites_identicos_al_servidor(self):
        r = self.client.get('/inicio/aprende')
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        for texto in ('id="apValor"', 'NOM-172-SEMARNAT-2023', 'Guías mundiales de calidad del aire', 'id="un-dia"'):
            self.assertIn(texto, html)
        payload = json.loads(re.search(r'<script id="apContaminantes" type="application/json">(.*?)</script>', html, re.S)[1])
        for clave, (_, unidad, decimales, topes, metodo) in CONTAMINANTES.items():
            config = payload[clave]
            self.assertEqual([b['tope'] for b in config['bandas'][:-1]], list(topes))
            self.assertEqual((config['unidad'], config['decimales'], config['metodo']), (unidad, decimales, metodo))
        self.assertIn('El valor elegido no es una medición', html)
        self.assertNotRegex(html, r'<(script|link)[^>]+(src|href)="https?://')


if __name__ == '__main__':
    unittest.main()
