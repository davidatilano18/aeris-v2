"""Reglas del resumen «¿Cómo está el aire?»: 18 horas, revisión excluida, bandas oficiales."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from aeris_web.estado import banda, rango_meses, read_estado
from data_ingestion import operations as ops

SENSOR = 1352676  # Corregidora en el catálogo versionado.


class EstadoTests(unittest.TestCase):
    def setUp(self):
        self.carpeta = tempfile.TemporaryDirectory()
        self.db = Path(self.carpeta.name) / 'aeris.db'
        with closing(sqlite3.connect(self.db)) as conn, conn:
            ops.ensure_db(conn)

    def tearDown(self):
        self.carpeta.cleanup()

    def dia(self, fecha_local, valores, revision=(), fuente='OpenAQ'):
        # Día local desde 00:00 de Querétaro (UTC-6 en 2026).
        inicio = datetime(fecha_local.year, fecha_local.month, fecha_local.day, 6, tzinfo=timezone.utc)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            for h, v in enumerate(valores):
                t = (inicio + timedelta(hours=h)).isoformat().replace('+00:00', 'Z')
                conn.execute("INSERT INTO mediciones VALUES (?,?,?,'pm25',?,'µg/m³')", (fuente, SENSOR, t, v))
                conn.execute("INSERT INTO calidad_mediciones(fuente,sensor_id,fecha_utc,contaminante,es_cero,es_extremo,"
                             "salto_abrupto,requiere_revision,version_reglas) VALUES (?,?,?,'pm25',0,?,?,?,'aeris_qc_v2')",
                             (fuente, SENSOR, t, int(h in revision), int(h in revision), int(h in revision)))

    def test_bandas_oficiales_2026(self):
        # Se redondea a entero antes de clasificar (NOM-172): 15.4 -> 15 (Buena), 15.5 -> 16 (Aceptable).
        self.assertEqual([banda(v) for v in (15, 15.4, 15.5, 25.4, 25.5, 79.4, 79.5, 130.4, 130.5)],
                         ['Buena', 'Buena', 'Aceptable', 'Aceptable', 'Mala', 'Mala', 'Muy mala', 'Muy mala',
                          'Extremadamente mala'])

    def test_dieciocho_horas_y_revision_excluida(self):
        self.dia(date(2026, 10, 1), [10] * 24)                      # válido, Buena
        self.dia(date(2026, 10, 2), [20] * 17)                      # 17 h: sin promedio
        self.dia(date(2026, 10, 3), [5] * 18 + [300] * 6, revision=range(18, 24))  # picos excluidos
        self.dia(date(2026, 10, 4), [5] * 12 + [250] * 8, revision=range(12, 20))  # queda en revisión
        e = read_estado(self.db, now=datetime(2026, 10, 10, tzinfo=timezone.utc))
        s = next(x for x in e['series'] if x['sensor_id'] == SENSOR)
        self.assertEqual((s['validos'], s['revision'], s['conteo']['Buena']), (2, 1, 2))
        self.assertEqual(e['resumen']['malos'], 0)
        self.assertEqual(max(p['media'] for p in e['picos']), 10)

    def test_rango_de_meses_con_y_sin_cambio_de_anio(self):
        self.assertEqual(rango_meses(date(2026, 9, 17), date(2026, 10, 19)), 'Sep–oct 2026')
        self.assertEqual(rango_meses(date(2021, 9, 7), date(2026, 10, 16)), 'Sep 2021 – oct 2026')
        self.assertEqual(rango_meses(date(2025, 5, 28), date(2025, 9, 30)), 'Jun–sep 2025')

    def test_antes_solo_cuenta_dias_previos_al_periodo_actual(self):
        self.dia(date(2026, 10, 1), [10] * 24)                              # periodo actual (API)
        self.dia(date(2025, 3, 1), [40] * 24, fuente='OpenAQ-Archive')      # antes: Mala
        self.dia(date(2026, 10, 1), [12] * 24, fuente='OpenAQ-Archive')     # mismo periodo: no cuenta
        a = read_estado(self.db, now=datetime(2026, 10, 10, tzinfo=timezone.utc))['anterior']
        self.assertEqual((a['dias'], a['malos'], a['periodo']), (1, 1, 'Mar 2025 · OpenAQ Archive'))

    def test_futuro_no_cuenta_y_base_sin_cambios(self):
        self.dia(date(2026, 10, 1), [30] * 24)
        antes = self.db.read_bytes()
        e = read_estado(self.db, now=datetime(2026, 9, 1, tzinfo=timezone.utc))
        self.assertIsNone(e['resumen'])
        self.assertEqual(self.db.read_bytes(), antes)


if __name__ == '__main__':
    unittest.main()
