"""Conector Open-Meteo CAMS: modelo por punto, horas UTC, sin imputación ni horas futuras."""
import json
import unittest
from datetime import datetime, timezone

from data_ingestion.ambiental import catalogo
from data_ingestion.ambiental.open_meteo_cams import interpretar, url


def respuesta(**cambios):
    datos = {'latitude': 20.599998, 'longitude': -100.299995, 'utc_offset_seconds': 0, 'elevation': 1856.0,
             'hourly_units': {'time': 'iso8601', 'pm2_5': 'μg/m³', 'pm10': 'μg/m³'},
             'hourly': {'time': ['2026-10-18T00:00', '2026-10-18T01:00', '2026-10-18T02:00'],
                        'pm2_5': [2.1, None, 1.9], 'pm10': [4.0, 3.5, 3.0]}}
    datos.update(cambios)
    return json.dumps(datos).encode()


class OpenMeteoCamsTests(unittest.TestCase):
    def test_horas_utc_sin_imputar_y_hasta_exclusivo(self):
        hasta = datetime(2026, 10, 18, 2, tzinfo=timezone.utc)
        registros, resumen = interpretar(respuesta(), 'cams:marques', 20.605872, -100.332292, hasta=hasta)
        self.assertEqual([(r['variable_id'], r['fecha'].hour, r['valor']) for r in registros],
                         [('pm25', 0, 2.1), ('pm10', 0, 4.0), ('pm10', 1, 3.5)])
        self.assertEqual(resumen['sin_valor'], 1)
        self.assertEqual(registros[0]['unidad_original'], 'μg/m³')
        self.assertEqual(registros[0]['tipo_reporte'], 'CAMS-global')

    def test_rechaza_desfase_unidad_o_punto_lejano(self):
        with self.assertRaises(ValueError):
            interpretar(respuesta(utc_offset_seconds=-21600), 'cams:marques', 20.605872, -100.332292)
        with self.assertRaises(ValueError):
            interpretar(respuesta(hourly_units={'time': 'iso8601', 'pm2_5': 'ppm', 'pm10': 'μg/m³'}),
                        'cams:marques', 20.605872, -100.332292)
        with self.assertRaises(ValueError):
            interpretar(respuesta(), 'cams:marques', 20.9, -100.332292)

    def test_url_pide_utc_y_dominio_global(self):
        u = url(20.6, -100.3, datetime(2023, 1, 1), datetime(2023, 6, 30))
        self.assertIn('timezone=GMT', u)
        self.assertIn('domains=cams_global', u)
        self.assertIn('start_date=2023-01-01', u)

    def test_catalogo_lo_marca_como_modelo(self):
        self.assertEqual(catalogo.FUENTES['open-meteo-cams']['tipo_producto'], 'modelo')
        marques = catalogo.ESTACIONES['cams:marques']
        self.assertEqual((marques['tipo_sitio'], marques['municipio']), ('punto_modelo', 'El Marqués'))


if __name__ == '__main__':
    unittest.main()
