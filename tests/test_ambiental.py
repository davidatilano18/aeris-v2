import csv
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from flask import Flask

from aeris_web.ambiental import register_ambiental
from data_ingestion import operations as ops
from data_ingestion.ambiental import actualizar, almacen, esquema, ghcnh, nasa_power
from data_ingestion.ambiental.descargas import FalloFuente, Respuesta, SinPublicacion, descargar

UTC = timezone.utc
EST = 'ghcnh:MXI0000MMQT'


def psv(filas):
    columnas = ['STATION', 'Station_name', 'DATE', 'Year', 'Month', 'Day', 'Hour', 'Minute'] + [
        f'{c}{s}' for c in ghcnh.COLUMNAS for s in ('', '_Measurement_Code', '_Quality_Code', '_Report_Type')]
    salida = io.StringIO()
    escritor = csv.DictWriter(salida, columnas, delimiter='|', restval='', lineterminator='\n')
    escritor.writeheader()
    for fecha, tipo, valores in filas:
        d = datetime.fromisoformat(fecha)
        fila = {'STATION': 'MXI0000MMQT', 'Station_name': 'QUERETARO INTERCONTINENTAL', 'DATE': fecha,
                'Year': d.year, 'Month': f'{d.month:02}', 'Day': f'{d.day:02}', 'Hour': f'{d.hour:02}',
                'Minute': f'{d.minute:02}'}
        for columna, valor in valores.items():
            valor, medicion, calidad = valor if isinstance(valor, tuple) else (valor, '', '')
            fila.update({columna: valor, columna + '_Measurement_Code': medicion,
                         columna + '_Quality_Code': calidad, columna + '_Report_Type': tipo})
        escritor.writerow(fila)
    return salida.getvalue()


ARCHIVO = psv([
    ('2026-10-18T02:40:00', 'FM15', {'temperature': '12.0', 'wind_direction': '80', 'altimeter': '1034.2'}),
    ('2026-10-18T03:00:00', 'FM94_1', {'temperature': '29.1'}),
    ('2026-10-18T03:20:00', 'FM16', {'temperature': '11.5'}),
    ('2026-10-18T03:41:00', 'FM15', {'temperature': ('11.0', '', '2'), 'wind_direction': ('999', 'C', ''),
                                     'relative_humidity': ('87', 'D', 'f')}),
    ('2026-10-18T04:41:00', 'FM15', {'temperature': '10.0', 'wind_direction': ('999', 'V', '')}),
])


def power(valores=None, lat=20.6173, lon=-100.1857):
    base = valores or {'2026101800': 1.0, '2026101801': -999.0}
    return json.dumps({'geometry': {'coordinates': [lon, lat, 2145.4]},
                       'header': {'fill_value': -999.0, 'sources': ['GEOSIT']},
                       'properties': {'parameter': {p: (dict(base, **{'2026101800': 80.2}) if p == 'PS' else base)
                                                    for p in nasa_power.PARAMETROS}}}).encode()


def respuesta(url, contenido, estado=200, etag=None):
    return Respuesta(url, estado, contenido, hashlib.sha256(contenido).hexdigest(), etag)


class Base(unittest.TestCase):
    def setUp(self):
        self.carpeta = tempfile.TemporaryDirectory()
        self.db = Path(self.carpeta.name) / 'dev.db'
        with closing(esquema.conectar(self.db)) as conn:
            esquema.migrar(conn)

    def tearDown(self):
        self.carpeta.cleanup()

    def conn(self):
        return closing(esquema.conectar(self.db))


class EsquemaTests(Base):
    def test_migrar_es_idempotente_y_revertir_solo_quita_amb(self):
        with self.conn() as conn:
            self.assertEqual(esquema.migrar(conn), 2)
            conn.execute('CREATE TABLE ajena (x)')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM amb_estaciones').fetchone()[0], 19)  # MMQT, 2 celdas POWER, 8 de la red y 8 puntos CAMS
            self.assertEqual(conn.execute('SELECT SUM(autorizada) FROM amb_fuentes').fetchone()[0], 0)
            esquema.revertir(conn)
            self.assertEqual(esquema.tablas(conn), {'ajena'})
            self.assertEqual(esquema.migrar(conn), 2)

    def test_revertir_por_version(self):
        def indices(c):
            return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'amb_%'")}
        with self.conn() as conn:
            self.assertNotIn('amb_observaciones_serie', indices(conn))
            self.assertEqual(esquema.revertir(conn, objetivo=1), 1)
            self.assertIn('amb_observaciones_serie', indices(conn))
            self.assertEqual(esquema.migrar(conn), 2)
            self.assertNotIn('amb_observaciones_serie', indices(conn))

    def test_revertir_con_datos_exige_confirmacion(self):
        with self.conn() as conn:
            ingesta = almacen.iniciar(conn, ghcnh.FUENTE)
            almacen.guardar(conn, ingesta, ghcnh.interpretar(ARCHIVO, 'MXI0000MMQT', EST)[0])
            with self.assertRaises(PermissionError):
                esquema.revertir(conn)
            esquema.revertir(conn, descartar_datos=True)
            self.assertFalse({t for t in esquema.tablas(conn) if t.startswith('amb_')})

    def test_base_con_mediciones_requiere_doble_autorizacion_y_no_altera_legado(self):
        legado = Path(self.carpeta.name) / 'legado.db'
        with closing(sqlite3.connect(legado)) as conn, conn:
            ops.ensure_db(conn)
            conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1,'2026-01-01T00:00:00Z','pm25',5,'µg/m³')")
        def huella(c):
            return (c.execute("SELECT name,sql FROM sqlite_master WHERE tbl_name NOT LIKE 'amb_%' ORDER BY name").fetchall(),
                    c.execute('SELECT * FROM mediciones').fetchall())
        with closing(esquema.conectar(legado)) as conn:
            antes = huella(conn)
            with self.assertRaises(PermissionError):
                esquema.migrar(conn)
            with self.assertRaises(PermissionError):
                esquema.migrar(conn, permitir_base_principal=True)
            with patch.dict(os.environ, {esquema.AUTORIZACION_ENV: 'autorizado'}):
                esquema.migrar(conn, permitir_base_principal=True)
                self.assertEqual(huella(conn), antes)
                esquema.revertir(conn, permitir_base_principal=True)
            self.assertEqual(huella(conn), antes)

    def test_coordenadas_de_estacion_no_se_reescriben(self):
        with self.conn() as conn:
            conn.execute("UPDATE amb_estaciones SET latitud=20.0 WHERE estacion_id=?", (EST,))
            with self.assertRaises(ValueError):
                esquema.sembrar(conn)


class GhcnhTests(unittest.TestCase):
    def test_solo_metar_y_convenciones_documentadas(self):
        registros, resumen = ghcnh.interpretar(ARCHIVO, 'MXI0000MMQT', EST)
        temperaturas = [(r['fecha'].isoformat(), r['tipo_reporte'], r['valor']) for r in registros
                        if r['variable_id'] == 'temperatura_aire']
        self.assertNotIn(29.1, [t[2] for t in temperaturas])
        self.assertEqual(resumen['valores_excluidos'], {'FM94_1': 1, 'direccion_999_no_calma': 1})
        calma = next(r for r in registros if r['variable_id'] == 'viento_direccion' and r['codigo_medicion'] == 'C')
        self.assertEqual((calma['valor'], calma['valor_original']), (0.0, '999'))
        marcas = {(r['variable_id'], r['fecha'].hour, r['fecha'].minute): r['marca_origen'] for r in registros}
        self.assertTrue(marcas[('temperatura_aire', 3, 41)])
        self.assertTrue(marcas[('humedad_relativa', 3, 41)])
        self.assertFalse(marcas[('temperatura_aire', 2, 40)])
        self.assertTrue(all(r['fecha'].tzinfo is UTC for r in registros))

    def test_ventana_y_rechazos_de_esquema(self):
        desde = datetime(2026, 10, 18, 3, tzinfo=UTC)
        hasta = datetime(2026, 10, 18, 4, tzinfo=UTC)
        registros, _ = ghcnh.interpretar(ARCHIVO, 'MXI0000MMQT', EST, desde, hasta)
        self.assertTrue(all(desde <= r['fecha'] < hasta for r in registros))
        with self.assertRaises(ValueError):
            ghcnh.interpretar(ARCHIVO, 'MXM00076626', EST)
        with self.assertRaises(ValueError):
            ghcnh.interpretar('STATION|DATE\nX|2026-01-01T00:00:00\n', 'X', EST)


class PowerTests(unittest.TestCase):
    def test_relleno_descartado_y_unidades(self):
        registros, resumen = nasa_power.interpretar(power(), 'power:mmqt', 20.6173, -100.1857)
        self.assertEqual(resumen['relleno_descartado'], len(nasa_power.PARAMETROS))
        presion = next(r for r in registros if r['variable_id'] == 'presion_superficie')
        self.assertEqual((presion['valor'], presion['unidad_original']), (802.0, 'kPa'))
        self.assertTrue(all(r['periodo'] == 'PT1H' for r in registros))

    def test_punto_distinto_se_rechaza(self):
        with self.assertRaises(ValueError):
            nasa_power.interpretar(power(lat=20.5), 'power:mmqt', 20.6173, -100.1857)


class AlmacenTests(Base):
    def guardar(self, texto=ARCHIVO, **kw):
        with self.conn() as conn:
            ingesta = almacen.iniciar(conn, ghcnh.FUENTE)
            return almacen.guardar(conn, ingesta, ghcnh.interpretar(texto, 'MXI0000MMQT', EST)[0], **kw)

    def test_idempotente_y_revision_sin_sobrescribir(self):
        primero = self.guardar()
        self.assertEqual((primero['insertadas'], primero['duplicadas']), (8, 0))
        self.assertEqual(self.guardar()['duplicadas'], 8)
        corregido = ARCHIVO.replace('|12.0|', '|12.5|')
        segundo = self.guardar(corregido)
        self.assertEqual((segundo['insertadas'], segundo['revisiones']), (0, 1))
        self.assertEqual(self.guardar(corregido)['revisiones'], 0)
        with self.conn() as conn:
            self.assertEqual(conn.execute("SELECT valor FROM amb_observaciones WHERE fecha_utc='2026-10-18T02:40:00Z' "
                                          "AND variable_id='temperatura_aire'").fetchone()[0], 12.0)
            for sql in ('UPDATE amb_observaciones SET valor=0', 'DELETE FROM amb_observaciones'):
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(sql)

    def test_rangos_valores_no_finitos_futuros_y_hora_local(self):
        registros = [
            {'estacion_id': EST, 'variable_id': 'temperatura_aire', 'fecha': datetime(2022, 6, 1, 12, tzinfo=UTC),
             'valor': 60.0, 'valor_original': '60.0', 'unidad_original': '°C', 'periodo': 'instantaneo',
             'tipo_reporte': 'FM-15'},
            {'estacion_id': EST, 'variable_id': 'temperatura_aire', 'fecha': datetime(2026, 6, 1, 12, tzinfo=UTC),
             'valor': float('nan'), 'valor_original': 'nan', 'unidad_original': '°C', 'periodo': 'instantaneo',
             'tipo_reporte': 'FM-15'},
            {'estacion_id': EST, 'variable_id': 'temperatura_aire', 'fecha': datetime(2030, 1, 1, tzinfo=UTC),
             'valor': 20.0, 'valor_original': '20.0', 'unidad_original': '°C', 'periodo': 'instantaneo',
             'tipo_reporte': 'FM-15'},
        ]
        with self.conn() as conn:
            conteos = almacen.guardar(conn, almacen.iniciar(conn, ghcnh.FUENTE), registros,
                                      ahora_utc=datetime(2026, 10, 20, tzinfo=UTC))
            self.assertEqual(conteos['motivos_descarte'], {'no_finito': 1, 'fecha_futura': 1})
            fila = conn.execute('SELECT fecha_local,fuera_de_rango FROM amb_observaciones').fetchone()
        self.assertEqual(fila, ('2022-06-01T07:00:00-05:00', 1))  # horario de verano vigente en 2022
        self.assertEqual(almacen.iso_local(datetime(2026, 6, 1, 12, tzinfo=UTC)), '2026-06-01T06:00:00-06:00')
        with self.assertRaises(ValueError):
            almacen.iso_utc(datetime(2026, 1, 1))


class DescargasTests(unittest.TestCase):
    class Abierta:
        def __init__(self, contenido=b'ok'):
            self.contenido, self.status, self.headers, self.url = contenido, 200, {'ETag': '"e1"'}, 'u'
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n): return self.contenido[:n]

    def secuencia(self, *eventos):
        pendientes = list(eventos)
        def abrir(req, timeout):
            evento = pendientes.pop(0)
            if isinstance(evento, Exception):
                raise evento
            return evento
        return abrir

    def http(self, codigo, cabeceras=None):
        return HTTPError('u', codigo, 'x', cabeceras or {}, None)

    def test_reintenta_y_respeta_retry_after(self):
        esperas = []
        r = descargar('https://fuente.test/a', abrir=self.secuencia(self.http(503), self.http(429, {'Retry-After': '7'}),
                                                URLError('red'), self.Abierta()), dormir=esperas.append)
        self.assertEqual((r.contenido, r.etag), (b'ok', '"e1"'))
        self.assertEqual(esperas, [2.0, 7.0, 8.0])

    def test_404_es_sin_publicacion_y_401_no_se_reintenta(self):
        with self.assertRaises(SinPublicacion):
            descargar('https://fuente.test/a', abrir=self.secuencia(self.http(404)), dormir=lambda s: None)
        with self.assertRaises(FalloFuente):
            descargar('https://fuente.test/a', abrir=self.secuencia(self.http(401)), dormir=self.fail)

    def test_limite_de_tamano_y_agotamiento(self):
        with self.assertRaises(FalloFuente):
            descargar('https://fuente.test/a', limite=1, intentos=1, abrir=self.secuencia(self.Abierta(b'abc')))
        with self.assertRaises(FalloFuente):
            descargar('https://fuente.test/a', intentos=2, abrir=self.secuencia(TimeoutError(), TimeoutError()), dormir=lambda s: None)

    def test_304_devuelve_sin_cambios(self):
        r = descargar('https://fuente.test/a', etag='"e1"', abrir=self.secuencia(self.http(304)))
        self.assertTrue(r.sin_cambios)


class ActualizarTests(Base):
    AHORA = datetime(2026, 10, 20, 15, tzinfo=UTC)  # 09:00 en Querétaro

    def autorizar(self, *fuentes):
        with self.conn() as conn:
            for f in fuentes:
                esquema.autorizar(conn, f)

    def falsa(self, fallar=(), sin_publicar=(), etag=None):
        llamadas = []
        def bajar(url, etag=None):
            llamadas.append((url, etag))
            if any(x in url for x in fallar):
                raise FalloFuente('HTTP 503')
            if any(x in url for x in sin_publicar):
                raise SinPublicacion('HTTP 404')
            if 'ghcnh' in url or 'GHCNh' in url:
                return respuesta(url, ARCHIVO.encode(), etag='"g1"')
            lat = 20.6173 if 'latitude=20.6173' in url else 20.552563888889
            lon = -100.1857 if lat == 20.6173 else -100.44580555556
            return respuesta(url, power(lat=lat, lon=lon))
        bajar.llamadas = llamadas
        return bajar

    def test_solo_fuentes_autorizadas_y_desde_explicito(self):
        self.autorizar(ghcnh.FUENTE)
        r = actualizar.ejecutar(self.db, [ghcnh.FUENTE, nasa_power.FUENTE], ahora=self.AHORA, bajar=self.falsa())
        self.assertEqual(r['no_autorizadas'], [nasa_power.FUENTE])
        self.assertEqual(r['resultados'][0]['estaciones'][EST], {'estado': 'requiere_desde_inicial'})
        r = actualizar.ejecutar(self.db, ahora=self.AHORA, desde_inicial=datetime(2026, 10, 1, tzinfo=UTC),
                                bajar=self.falsa())
        self.assertEqual((r['estado'], r['resultados'][0]['insertadas']), ('correcto', 8))
        self.assertEqual(r['integridad'], {'integrity_check': 'ok', 'foreign_key_violations': 0})

    def test_incremental_con_solapamiento_y_etag(self):
        self.autorizar(ghcnh.FUENTE)
        actualizar.ejecutar(self.db, ahora=self.AHORA, desde_inicial=datetime(2026, 10, 1, tzinfo=UTC), bajar=self.falsa())
        bajar = self.falsa()
        r = actualizar.ejecutar(self.db, ahora=self.AHORA, bajar=bajar)
        self.assertEqual((r['resultados'][0]['estado'], r['resultados'][0]['duplicadas']), ('sin_datos_nuevos', 8))
        self.assertEqual(bajar.llamadas[0][1], '"g1"')
        self.assertEqual(r['resultados'][0]['estaciones'][EST]['desde'], '2026-10-15T04:41:00Z')

    def test_rellenar_usa_desde_sin_retroceder_estado(self):
        self.autorizar(ghcnh.FUENTE)
        actualizar.ejecutar(self.db, ahora=self.AHORA, desde_inicial=datetime(2026, 10, 1, tzinfo=UTC), bajar=self.falsa())
        bajar = self.falsa()
        r = actualizar.ejecutar(self.db, ahora=self.AHORA, desde_inicial=datetime(2024, 3, 1, tzinfo=UTC),
                                bajar=bajar, rellenar=True)
        self.assertEqual([u.split('/by-year/')[1][:4] for u, _ in bajar.llamadas], ['2024', '2025', '2026'])
        self.assertEqual(r['resultados'][0]['insertadas'], 0)
        with self.conn() as conn:
            self.assertEqual(almacen.estado(conn, EST)[0], '2026-10-18T04:41:00Z')

    def test_fallo_de_una_estacion_no_impide_las_demas(self):
        self.autorizar(nasa_power.FUENTE)
        r = actualizar.ejecutar(self.db, ahora=self.AHORA, desde_inicial=datetime(2026, 10, 18, tzinfo=UTC),
                                bajar=self.falsa(fallar=('latitude=20.6173',)))
        resultado = r['resultados'][0]
        self.assertEqual((r['estado'], resultado['estado']), ('con_fallos', 'fallo'))
        self.assertEqual(resultado['estaciones']['power:mmqt']['estado'], 'fallo')
        self.assertGreater(resultado['insertadas'], 0)

    def test_sin_publicacion_no_inventa_registros(self):
        self.autorizar(ghcnh.FUENTE)
        r = actualizar.ejecutar(self.db, ahora=self.AHORA, desde_inicial=datetime(2026, 10, 1, tzinfo=UTC),
                                bajar=self.falsa(sin_publicar=('GHCNh',)))
        self.assertEqual((r['estado'], r['resultados'][0]['estado']), ('correcto', 'sin_publicacion'))
        with self.conn() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM amb_observaciones').fetchone()[0], 0)

    def test_si_corresponde_una_vez_al_dia_desde_las_ocho(self):
        self.autorizar(ghcnh.FUENTE)
        temprano = datetime(2026, 10, 20, 13, 59, tzinfo=UTC)  # 07:59 local
        self.assertEqual(actualizar.ejecutar(self.db, si_corresponde=True, ahora=temprano, bajar=self.fail)['estado'],
                         'no_corresponde')
        desde = datetime(2026, 10, 1, tzinfo=UTC)
        self.assertEqual(actualizar.ejecutar(self.db, si_corresponde=True, ahora=self.AHORA, desde_inicial=desde,
                                             bajar=self.falsa())['estado'], 'correcto')
        self.assertEqual(actualizar.ejecutar(self.db, si_corresponde=True, ahora=self.AHORA, bajar=self.fail)['estado'],
                         'no_corresponde')

    def test_rechaza_base_principal_y_bloqueo_concurrente(self):
        legado = Path(self.carpeta.name) / 'legado.db'
        with closing(sqlite3.connect(legado)) as conn, conn:
            ops.ensure_db(conn)
        with self.assertRaises(PermissionError):
            actualizar.ejecutar(legado, ahora=self.AHORA, bajar=self.fail)
        self.autorizar(ghcnh.FUENTE)
        with ops.exclusive_lock(Path(str(self.db.resolve()) + '.ambiental.lock')):
            with self.assertRaises(OSError):
                actualizar.ejecutar(self.db, ahora=self.AHORA, desde_inicial=self.AHORA, bajar=self.falsa())

    def test_base_principal_autorizada_respalda_y_conserva_legado(self):
        legado = Path(self.carpeta.name) / 'principal.db'
        with closing(sqlite3.connect(legado)) as conn, conn:
            ops.ensure_db(conn)
            conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1,'2026-01-01T00:00:00Z','pm25',5,'µg/m³')")
        with patch.dict(os.environ, {esquema.AUTORIZACION_ENV: 'autorizado'}):
            with closing(esquema.conectar(legado)) as conn:
                esquema.migrar(conn, permitir_base_principal=True)
                esquema.autorizar(conn, ghcnh.FUENTE)
            antes = actualizar.huella_legada(legado)
            r = actualizar.ejecutar(legado, permitir_base_principal=True, ahora=self.AHORA,
                                    desde_inicial=datetime(2026, 10, 1, tzinfo=UTC), bajar=self.falsa())
        self.assertEqual((r['estado'], r['legado_intacto'], r['resultados'][0]['insertadas']), ('correcto', True, 8))
        respaldo = Path(r['respaldo']['ruta'])
        self.assertTrue(respaldo.is_file() and respaldo.parent.name == 'backups')
        self.assertEqual(actualizar.huella_legada(respaldo), antes)
        self.assertEqual(actualizar.huella_legada(legado), antes)

    def test_diario_desactivado_por_defecto_y_nunca_lanza(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(actualizar.DIARIO_ENV, None)
            self.assertEqual(actualizar.diario(self.db, bajar=self.fail), {'estado': 'desactivado'})
        vacia = Path(self.carpeta.name) / 'vacia.db'
        sqlite3.connect(vacia).close()
        with patch.dict(os.environ, {actualizar.DIARIO_ENV: 'apply'}):
            r = actualizar.diario(vacia, bajar=self.fail)
        self.assertEqual((r['estado'], r['error_tipo']), ('fallo_entrada', 'RuntimeError'))
        self.assertTrue(Path(r['reporte']).is_file())

    def test_diario_activado_ejecuta_una_vez_por_dia(self):
        self.autorizar(ghcnh.FUENTE)
        with closing(esquema.conectar(self.db)) as conn:
            ingesta = almacen.iniciar(conn, ghcnh.FUENTE, inicio=datetime(2026, 10, 1, tzinfo=UTC))
            almacen.guardar(conn, ingesta, ghcnh.interpretar(ARCHIVO, 'MXI0000MMQT', EST)[0])
            almacen.actualizar_estado(conn, EST, datetime(2026, 10, 18, 4, 41, tzinfo=UTC), ingesta)
            almacen.cerrar(conn, ingesta, 'exito')
        with patch.dict(os.environ, {actualizar.DIARIO_ENV: 'apply'}):
            self.assertEqual(actualizar.diario(self.db, bajar=self.falsa(), ahora=self.AHORA)['estado'], 'correcto')
            self.assertEqual(actualizar.diario(self.db, bajar=self.fail, ahora=self.AHORA)['estado'], 'no_corresponde')

    def test_cli_escribe_reporte_sin_borrar_nada(self):
        self.autorizar(ghcnh.FUENTE)
        with patch.object(actualizar, 'descargar', self.falsa()), patch('builtins.print'):
            codigo = actualizar.main(['--db', str(self.db), '--desde', '2026-10-01T00:00:00Z'])
        self.assertEqual(codigo, 0)
        carpeta = self.db.parent / 'sync_runtime' / 'ambiental'
        self.assertTrue((carpeta / 'ultimo_correcto.json').is_file())


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        with self.conn() as conn:
            ingesta = almacen.iniciar(conn, ghcnh.FUENTE)
            almacen.guardar(conn, ingesta, ghcnh.interpretar(ARCHIVO, 'MXI0000MMQT', EST)[0])
            almacen.cerrar(conn, ingesta, 'exito')
        app = Flask(__name__)
        register_ambiental(app, lambda: self.db)
        self.cliente = app.test_client()

    def get(self, ruta):
        return self.cliente.get('/api/ambiental/v1/' + ruta)

    def test_catalogos(self):
        fuentes = self.get('fuentes').get_json()['fuentes']
        self.assertEqual({f['fuente_id']: f['tipo_producto'] for f in fuentes},
                         {'nasa-power': 'reanalisis', 'noaa-ghcnh': 'observacion', 'open-meteo-cams': 'modelo', 'openaq-archivo': 'observacion'})
        estaciones = self.get('estaciones?municipio=El%20Marqu%C3%A9s').get_json()['estaciones']
        self.assertEqual({e['estacion_id'] for e in estaciones}, {EST, 'power:mmqt', 'openaq:235221', 'cams:marques'})
        self.assertIn('temperatura_aire', {v['variable_id'] for v in self.get('variables').get_json()['variables']})
        self.assertEqual(self.get('ingestas').get_json()['ingestas'][0]['estado'], 'exito')

    def test_observaciones_originales_y_horarias(self):
        base = f'observaciones?estacion={EST}&variable=temperatura_aire&desde=2026-10-18T00:00:00Z&hasta=2026-10-19T00:00:00Z'
        original = self.get(base).get_json()['series']['temperatura_aire']['puntos']
        self.assertEqual([p['tipo_reporte'] for p in original], ['FM-15', 'FM-16', 'FM-15', 'FM-15'])
        horaria = self.get(base + '&resolucion=hora').get_json()['series']['temperatura_aire']['puntos']
        self.assertEqual([(p['fecha_utc'], p['valor']) for p in horaria],
                         [('2026-10-18T02:00:00Z', 12.0), ('2026-10-18T03:00:00Z', 11.0), ('2026-10-18T04:00:00Z', 10.0)])
        limpia = self.get(base + '&incluir_marcadas=0').get_json()['series']['temperatura_aire']['puntos']
        self.assertNotIn(11.0, [p['valor'] for p in limpia])

    def test_hora_con_solo_fm16_no_se_pierde(self):
        from aeris_web.ambiental import por_hora
        puntos = [{'fecha_utc': '2026-10-18T05:10:00Z', 'periodo': 'instantaneo', 'tipo_reporte': 'FM-15', 'valor': 9.0},
                  {'fecha_utc': '2026-10-18T05:40:00Z', 'periodo': 'instantaneo', 'tipo_reporte': 'FM-16', 'valor': 9.5}]
        self.assertEqual([(p['fecha_utc'], p['fecha_local'], p['fecha_observacion_utc'], p['valor']) for p in por_hora(puntos)],
                         [('2026-10-18T05:00:00Z', '2026-10-17T23:00:00-06:00', '2026-10-18T05:40:00Z', 9.5)])

    def test_validaciones(self):
        self.assertEqual(self.get('observaciones?variable=temperatura_aire').status_code, 400)
        self.assertEqual(self.get(f'observaciones?estacion={EST}&variable=x').status_code, 400)
        self.assertEqual(self.get(f'observaciones?estacion={EST}&variable=temperatura_aire&desde=2026-10-18T00:00:00').status_code, 400)
        self.assertEqual(self.get('observaciones?estacion=nada&variable=temperatura_aire').status_code, 404)
        self.assertEqual(self.get('fuentes?x=1').status_code, 400)

    def test_cobertura(self):
        datos = self.get(f'cobertura?estacion={EST}&variable=temperatura_aire&desde=2026-10-18T00:00:00Z'
                         '&hasta=2026-10-18T12:00:00Z').get_json()
        v = datos['variables'][0]
        self.assertEqual((v['horas_esperadas'], v['horas_con_dato']), (12, 3))
        self.assertEqual([(h['desde_utc'], h['horas']) for h in v['huecos_3h_o_mas']], [('2026-10-18T05:00:00Z', 7)])

    def test_base_sin_migrar_es_503(self):
        otra = Path(self.carpeta.name) / 'vacia.db'
        sqlite3.connect(otra).close()
        app = Flask(__name__)
        register_ambiental(app, lambda: otra)
        self.assertEqual(app.test_client().get('/api/ambiental/v1/fuentes').status_code, 503)


if __name__ == '__main__':
    unittest.main()
