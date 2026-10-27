import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from alertas import bot, lecturas, store

NOW = datetime(2026, 10, 27, 20, 30, tzinfo=timezone.utc)


def mediciones(path, rows, qc=()):
    with sqlite3.connect(path) as conn:
        conn.executescript('''
            CREATE TABLE mediciones (fuente TEXT NOT NULL, sensor_id INTEGER NOT NULL, fecha_utc TEXT NOT NULL,
                contaminante TEXT NOT NULL, valor REAL NOT NULL, unidad TEXT,
                PRIMARY KEY (fuente, sensor_id, fecha_utc, contaminante));
            CREATE TABLE sensores (fuente TEXT NOT NULL, sensor_id INTEGER NOT NULL, location_id INTEGER NOT NULL,
                nombre TEXT NOT NULL, municipio TEXT NOT NULL, latitud REAL, longitud REAL,
                proveedor TEXT, metadatos_utc TEXT, PRIMARY KEY(fuente,sensor_id));
            CREATE TABLE calidad_mediciones (fuente TEXT NOT NULL, sensor_id INTEGER NOT NULL, fecha_utc TEXT NOT NULL,
                contaminante TEXT NOT NULL, es_cero INTEGER NOT NULL DEFAULT 0, es_extremo INTEGER NOT NULL DEFAULT 0,
                salto_abrupto INTEGER NOT NULL DEFAULT 0, requiere_revision INTEGER NOT NULL DEFAULT 0,
                version_reglas TEXT NOT NULL DEFAULT 'aeris_qc_v1',
                PRIMARY KEY (fuente, sensor_id, fecha_utc, contaminante));
            INSERT INTO sensores VALUES ('OpenAQ',10,1,'Josefa Vergara','Querétaro',NULL,NULL,NULL,NULL),
                ('OpenAQ',20,2,'Corregidora','Corregidora',NULL,NULL,NULL,NULL),
                ('OpenAQ',30,3,'Histórica','El Marqués',NULL,NULL,NULL,NULL);''')
        conn.executemany("INSERT INTO mediciones VALUES ('OpenAQ',?,?,'pm25',?,'µg/m³')", rows)
        conn.executemany("INSERT INTO calidad_mediciones(fuente,sensor_id,fecha_utc,contaminante,requiere_revision) "
                         "VALUES ('OpenAQ',?,?,'pm25',1)", qc)
    conn.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        folder = Path(self.folder.name)
        self.med = folder / 'mediciones.db'
        mediciones(self.med, [(10, '2026-10-27T18:00:00Z', 31.4), (10, '2026-10-27T17:00:00Z', 20),
                              (20, '2026-10-27T19:00:00Z', 12), (30, '2021-09-23T10:00:00Z', 50),
                              (20, '2026-10-28T19:00:00Z', 99)],  # futura: se ignora
                   qc=[(10, '2026-10-27T18:00:00Z')])
        self.conn = store.conectar(folder / 'alertas.db')
        self.bot = bot.Bot(self.conn, self.med, now=lambda: NOW)

    def tearDown(self):
        self.conn.close()
        self.folder.cleanup()

    def say(self, text, chat=111): return self.bot.responder(chat, text)


class LecturasTests(Base):
    def test_latest_per_active_station_sorted_and_numbered(self):
        lista = lecturas.estaciones(self.med, NOW)
        self.assertEqual([(1, 20, 12.0, None), (2, 10, 31.4, True)],
                         [(e['numero'], e['sensor_id'], e['valor'], e['revision']) for e in lista])
        self.assertAlmostEqual(2.5, lista[1]['edad_horas'])


class BotTests(Base):
    def test_start_registers_and_explains(self):
        self.assertIn('/suscribir', self.say('/start'))
        self.assertIsNotNone(store.suscriptor(self.conn, 111))
        self.assertIn('Primero envía /start', self.say('/suscribir 1', chat=222))

    def test_ahora_and_estaciones(self):
        ahora = self.say('/ahora@AERIS_QRO_BOT')
        self.assertIn('1. Corregidora: 12 µg/m³ a las 27/10 13:00', ahora)
        self.assertIn('2. Josefa Vergara: 31 µg/m³ a las 27/10 12:00 (en revisión)', ahora)
        self.assertNotIn('Histórica', ahora)
        self.assertIn('2. Josefa Vergara (Querétaro)', self.say('/estaciones'))

    def test_subscribe_default_custom_all_and_cancel(self):
        self.say('/start')
        self.assertIn('Corregidora supere 25', self.say('/suscribir 1'))
        self.assertIn('Josefa Vergara supere 33.5', self.say('/suscribir 2 33,5'))
        self.assertIn('todas las estaciones', self.say('/suscribir todas 40'))
        mias = self.say('/mis_alertas')
        self.assertIn('Todas las estaciones: 40', mias)
        self.assertIn('Corregidora: 25', mias)
        self.assertIn('Cancelada', self.say('/cancelar 1'))
        self.assertIn('No tenías', self.say('/cancelar 1'))
        self.assertEqual([None, 10], [s['sensor_id'] for s in store.suscripciones(self.conn, 111)])

    def test_bad_input_is_explained_not_raised(self):
        self.say('/start')
        limiter = bot.Limitador()
        for text, expected in (('/suscribir 9', 'No hay estación'), ('/suscribir 1 mucho', 'debe ser un número'),
                               ('/suscribir 1 5000', 'entre 0 y 1000'), ('/silencio 25 7', 'horas de 0 a 23'), ('/silencio 7', 'Uso'),
                               ('/silencio 7 7', 'distintas'), ('/inventado', 'No conozco'), ('hola', '/ayuda')):
            update = {'update_id': 1, 'message': {'chat': {'id': 111, 'type': 'private'}, 'text': text}}
            self.assertIn(expected, bot.procesar(self.bot, update, limiter)[1], text)

    def test_quiet_pause_and_baja(self):
        self.say('/start'); self.say('/suscribir 1')
        self.assertIn('23:00 a 7:00', self.say('/silencio 23 7'))
        self.say('/pausa')
        mias = self.say('/mis_alertas')
        self.assertIn('Silencio de 23:00 a 7:00', mias)
        self.assertIn('en pausa', mias)
        self.assertEqual([], store.activas(self.conn))
        self.say('/reanudar')
        self.assertEqual(1, len(store.activas(self.conn)))
        self.assertIn('borré', self.say('/baja'))
        self.assertIsNone(store.suscriptor(self.conn, 111))

    def test_ignores_groups_long_texts_and_floods(self):
        def update(text='/ayuda', kind='private'):
            return {'update_id': 1, 'message': {'chat': {'id': 111, 'type': kind}, 'text': text}}
        clock = [0.0]
        limiter = bot.Limitador(maximo=3, reloj=lambda: clock[0])
        self.assertIsNone(bot.procesar(self.bot, update(kind='group'), limiter))
        self.assertIsNone(bot.procesar(self.bot, update('/ayuda ' + 'x' * 300), limiter))
        self.assertIsNone(bot.procesar(self.bot, {'update_id': 1, 'message': {'chat': {'id': 111, 'type': 'private'}}}, limiter))
        self.assertEqual(3, sum(bot.procesar(self.bot, update(), limiter) is not None for _ in range(5)))
        clock[0] = 61
        self.assertIsNotNone(bot.procesar(self.bot, update(), limiter))

    def test_unreadable_measurements_do_not_crash(self):
        broken = bot.Bot(self.conn, Path(self.folder.name) / 'no_existe.db', now=lambda: NOW)
        self.assertEqual(bot.SIN_DATOS, broken.responder(111, '/ahora'))


class FakeApi:
    def __init__(self, batches):
        self.batches, self.sent, self.calls = list(batches), [], []

    def call(self, method, **params):
        self.calls.append(method)
        if method == 'getUpdates':
            item = self.batches.pop(0)
            if isinstance(item, Exception): raise item
            return item
        return True

    def send(self, chat_id, text): self.sent.append((chat_id, text))


class RunTests(Base):
    def test_loop_answers_retries_and_never_sends_to_groups(self):
        msg = lambda uid, chat, kind, text: {'update_id': uid, 'message': {'chat': {'id': chat, 'type': kind}, 'text': text}}
        api = FakeApi([[msg(1, 111, 'private', '/start'), msg(2, -5, 'group', '/start')],
                       bot.TelegramError(502), OSError('red'), [msg(3, 111, 'private', '/ayuda')]])
        waits = []
        bot.run(api, self.bot, stop=lambda: not api.batches, pausa=waits.append)
        self.assertEqual('setMyCommands', api.calls[0])
        self.assertEqual([111, 111], [c for c, _ in api.sent])
        self.assertEqual([5, 10], waits)

    def test_invalid_token_stops(self):
        api = FakeApi([bot.TelegramError(401)])
        with self.assertRaises(bot.TelegramError):
            bot.run(api, self.bot, stop=lambda: False, pausa=lambda s: None)

    def test_token_is_not_in_repr(self):
        self.assertNotIn('123:secreto', repr(bot.Telegram('123:secreto')))


if __name__ == '__main__':
    unittest.main()
