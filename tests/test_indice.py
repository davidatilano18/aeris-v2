"""Índice AIRE Y SALUD completo y conector del archivo OpenAQ para contaminantes distintos de PM2.5."""
import unittest
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aeris_web.indice import BANDAS, banda, concentracion_diaria, maximo_movil_8h, redondear, requiere_revision
from data_ingestion.ambiental.openaq_archivo import interpretar

ZONA = ZoneInfo('America/Mexico_City')


class RedondeoYBandasTests(unittest.TestCase):
    def test_ejemplos_de_redondeo_de_la_norma(self):
        # NOM-172-SEMARNAT-2023, reglas a), b) y c).
        self.assertEqual(redondear(0.0955, 3), 0.096)
        self.assertEqual(redondear(0.0954, 3), 0.095)
        self.assertEqual(redondear(9.4, 0), 9)
        self.assertEqual(redondear(9.5, 0), 10)
        self.assertEqual(redondear(11.324, 2), 11.32)
        self.assertEqual(redondear(11.035, 2), 11.04)

    def test_limites_por_contaminante(self):
        casos = {
            'pm25': [(15.4, 'Buena'), (15.5, 'Aceptable'), (25.5, 'Mala'), (130.5, 'Extremadamente mala')],
            'pm10': [(45, 'Buena'), (45.5, 'Aceptable'), (50.5, 'Mala'), (213.5, 'Extremadamente mala')],
            'o3': [(0.0584, 'Buena'), (0.0585, 'Aceptable'), (0.0905, 'Mala'), (0.1755, 'Extremadamente mala')],
            'no2': [(0.053, 'Buena'), (0.0535, 'Aceptable'), (0.2135, 'Extremadamente mala')],
            'so2': [(0.035, 'Buena'), (0.0355, 'Aceptable'), (0.3045, 'Extremadamente mala')],
            'co': [(5.004, 'Buena'), (5.005, 'Aceptable'), (16.005, 'Extremadamente mala')],
        }
        for contaminante, pares in casos.items():
            for valor, esperada in pares:
                self.assertEqual(banda(contaminante, valor)[0], esperada, (contaminante, valor))


class CalculoDiarioTests(unittest.TestCase):
    def horas(self, valores, dia=date(2026, 5, 1)):
        inicio = datetime(dia.year, dia.month, dia.day, tzinfo=ZONA)
        return {inicio + timedelta(hours=i): v for i, v in enumerate(valores) if v is not None}

    def test_promedio_decimal_exacto_antes_de_redondear(self):
        # Caso de la revisión de Codex: en binario 484.5/19 da 25.4999… (Aceptable); exacto es 25.5 -> 26 (Mala).
        base = concentracion_diaria('pm25', self.horas([25.455] * 18 + [26.31]))
        self.assertEqual(banda('pm25', base), ('Mala', 26.0))

    def test_maximo_horario_exige_18_horas(self):
        self.assertEqual(concentracion_diaria('o3', self.horas([0.03] * 17 + [0.09])), 0.09)
        self.assertIsNone(concentracion_diaria('o3', self.horas([0.03] * 17)))

    def test_promedio_24h_particulas(self):
        self.assertAlmostEqual(concentracion_diaria('pm10', self.horas([40] * 12 + [60] * 12)), 50)

    def test_co_movil_8h_con_minimo_de_6_horas(self):
        serie = self.horas([1.0] * 10 + [9.0] * 8 + [1.0] * 6)
        self.assertAlmostEqual(maximo_movil_8h(serie, date(2026, 5, 1)), 9.0)
        # Con solo 5 horas en la ventana no hay promedio móvil.
        escasa = self.horas([None, None, None, 2.0, 2.0, 2.0, 2.0, 2.0])
        self.assertIsNone(maximo_movil_8h(escasa, date(2026, 5, 1)))

    def test_revision_gases_marca_extremos_y_saltos_sin_mirar_adelante(self):
        horas = self.horas([0.02, 0.03, 0.20, 0.03, 0.04, 0.18])
        marcadas = sorted(t.hour for t in requiere_revision('o3', horas))
        # 0.20 (salto de 0.17 > 0.135), 0.03 tras 0.20 (salto) y 0.18 (> 0.175: extremo).
        self.assertEqual(marcadas, [2, 3, 5])
        # Un hueco de más de una hora no cuenta como salto.
        hueco = self.horas([1.0, None, None, 13.5])
        self.assertEqual(requiere_revision('co', hueco), set())

    def test_ventanas_en_utc_con_horario_de_verano(self):
        # 30/10/2022: último cambio de horario en Querétaro; ese día local tiene 25 horas.
        dia = date(2022, 10, 30)
        inicio = datetime(2022, 10, 30, tzinfo=ZONA).astimezone(timezone.utc)
        serie = {(inicio + timedelta(hours=k)).astimezone(ZONA): 1.0 for k in range(-7, 25)}
        serie[(inicio + timedelta(hours=24)).astimezone(ZONA)] = 9.0  # última hora real del día local
        # Con 8 horas, la ventana que termina en esa hora promedia (7 × 1 + 9) / 8 = 2.
        self.assertEqual(maximo_movil_8h(serie, dia), 2)
        # Dos horas consecutivas en UTC con la misma hora de reloj (01:00 repetida) son adyacentes.
        a = datetime(2022, 10, 30, 7, tzinfo=timezone.utc).astimezone(ZONA)
        b = datetime(2022, 10, 30, 8, tzinfo=timezone.utc).astimezone(ZONA)
        self.assertEqual(requiere_revision('o3', {a: 0.02, b: 0.20}), {b})

    def test_bandas_en_orden(self):
        self.assertEqual(BANDAS[0], 'Buena')
        self.assertEqual(BANDAS[-1], 'Extremadamente mala')


class ConectorArchivoTests(unittest.TestCase):
    ENCABEZADO = '"location_id","sensors_id","location","datetime","lat","lon","parameter","units","value"\n'

    def test_separa_pm25_y_rechaza_unidades_no_canonicas(self):
        texto = self.ENCABEZADO + '\n'.join([
            '235225,1,"COR","2025-07-16T01:00:00-06:00","20.5","-100.4","pm25","µg/m³","19.12"',
            '235225,2,"COR","2025-07-16T01:00:00-06:00","20.5","-100.4","o3","ppm","0.04117"',
            '235225,3,"COR","2025-07-16T01:00:00-06:00","20.5","-100.4","no2","µg/m³","40"',
            '235225,4,"COR","2025-07-16T01:00:00-06:00","20.5","-100.4","nox","ppm","0.02"',
            '999999,5,"X","2025-07-16T01:00:00-06:00","20.5","-100.4","co","ppm","0.3"',
        ])
        registros, descartes = interpretar(texto, {235225: 'openaq:235225'})
        self.assertEqual([(r['variable_id'], r['valor_original']) for r in registros], [('o3', '0.04117')])
        r = registros[0]
        self.assertEqual(r['fecha'], datetime(2025, 7, 16, 7, tzinfo=timezone.utc))  # -06:00 a UTC, sin desplazar
        self.assertEqual((r['estacion_id'], r['codigo_medicion'], r['unidad_original']), ('openaq:235225', 'sensor 2', 'ppm'))
        self.assertEqual(descartes, {'unidad_no_canonica': 1, 'ubicacion_fuera_de_catalogo': 1})

    def test_fecha_sin_zona_se_descarta(self):
        texto = self.ENCABEZADO + '235225,2,"COR","2025-07-16T01:00:00","20.5","-100.4","o3","ppm","0.04"'
        registros, descartes = interpretar(texto, {235225: 'openaq:235225'})
        self.assertEqual((registros, descartes), ([], {'fecha_sin_zona': 1}))


if __name__ == '__main__':
    unittest.main()
