import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alertas import bot, evaluar, store
from tests.test_alertas_bot import mediciones

NOW = datetime(2026, 10, 27, 20, 30, tzinfo=timezone.utc)  # 14:30 en Querétaro


def estacion(sid, valor, horas=2.5, revision=False, nombre=None):
    fecha = (NOW - timedelta(hours=horas)).replace(minute=0, second=0)
    return {'sensor_id': sid, 'nombre': nombre or f'E{sid}', 'valor': valor, 'revision': revision,
            'fecha_utc': fecha, 'edad_horas': (NOW - fecha).total_seconds() / 3600}


def sub(id=1, chat=111, sid=10, umbral=25, silencio=(None, None)):
    return {'id': id, 'chat_id': chat, 'sensor_id': sid, 'umbral': umbral,
            'silencio_desde': silencio[0], 'silencio_hasta': silencio[1]}


class PlanearTests(unittest.TestCase):
    def plan(self, subs, estaciones, previos=None):
        previos = previos or {}
        return evaluar.planear(subs, estaciones, lambda s, sid: previos.get((s, sid)), NOW)

    def test_crossing_only_once_then_back_down_with_hysteresis(self):
        alto = {(1, 10): {'tipo': 'supera', 'fecha_utc': '2026-10-27T15:00:00Z'}}
        bajo = {(1, 10): {'tipo': 'normaliza', 'fecha_utc': '2026-10-27T15:00:00Z'}}
        self.assertEqual(['supera'], [e['tipo'] for e in self.plan([sub()], [estacion(10, 30)])])
        self.assertEqual([], self.plan([sub()], [estacion(10, 25)]))  # igual al umbral no supera
        self.assertEqual([], self.plan([sub()], [estacion(10, 40)], alto))  # sigue alto: no repite
        self.assertEqual([], self.plan([sub()], [estacion(10, 23)], alto))  # dentro del margen del 90 %
        self.assertEqual(['normaliza'], [e['tipo'] for e in self.plan([sub()], [estacion(10, 22)], alto)])
        self.assertEqual([], self.plan([sub()], [estacion(10, 10)], bajo))
        self.assertEqual(['supera'], [e['tipo'] for e in self.plan([sub()], [estacion(10, 30)], bajo)])

    def test_same_reading_is_never_evaluated_twice(self):
        lectura = estacion(10, 10)
        previo = {(1, 10): {'tipo': 'supera', 'fecha_utc': lectura['fecha_utc'].isoformat().replace('+00:00', 'Z')}}
        self.assertEqual([], self.plan([sub()], [lectura], previo))

    def test_ignores_zero_old_and_unknown_station(self):
        self.assertEqual([], self.plan([sub()], [estacion(10, 0)]))
        self.assertEqual([], self.plan([sub()], [estacion(10, 80, horas=5)]))
        self.assertEqual([], self.plan([sub(sid=99)], [estacion(10, 80)]))

    def test_all_stations_and_review_flag(self):
        eventos = self.plan([sub(sid=None)], [estacion(10, 30), estacion(20, 10), estacion(30, 120, revision=True)])
        self.assertEqual([(10, False), (30, True)], [(e['sensor_id'], e['revision']) for e in eventos])

    def test_quiet_hours_cross_midnight(self):
        self.assertTrue(evaluar.en_silencio(23, 7, 2))
        self.assertFalse(evaluar.en_silencio(23, 7, 14))
        self.assertTrue(evaluar.en_silencio(13, 16, 14))
        self.assertEqual([], self.plan([sub(silencio=(13, 16))], [estacion(10, 30)]))
        self.assertEqual(1, len(self.plan([sub(silencio=(23, 7))], [estacion(10, 30)])))

    def test_message_groups_and_dedupes_station(self):
        eventos = self.plan([sub(1, sid=10), sub(2, sid=None, umbral=20)],
                            [estacion(10, 30, nombre='Corregidora'), estacion(20, 50, revision=True, nombre='Josefa')])
        texto = evaluar.mensaje(eventos)
        self.assertEqual(1, texto.count('Corregidora'))
        self.assertIn('Josefa: 50 µg/m³', texto)
        self.assertIn('(lectura en revisión)', texto)
        self.assertIn('no un índice de salud', texto)


class FakeApi:
    def __init__(self, fallas=None):
        self.fallas, self.sent = dict(fallas or {}), []

    def send(self, chat_id, text):
        if chat_id in self.fallas: raise self.fallas[chat_id]
        self.sent.append((chat_id, text))


class EvaluarTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        folder = Path(self.folder.name)
        self.med = folder / 'mediciones.db'
        mediciones(self.med, [(10, '2026-10-27T18:00:00Z', 40), (20, '2026-10-27T18:00:00Z', 30)])
        self.conn = store.conectar(folder / 'alertas.db')
        for chat in (111, 222, 333):
            store.alta(self.conn, chat)
            store.suscribir(self.conn, chat, store.TODAS, 25)

    def tearDown(self):
        self.conn.close()
        self.folder.cleanup()

    def run_eval(self, api): return evaluar.evaluar(self.conn, api, self.med, NOW, log=lambda m: None)

    def test_sends_once_records_and_pauses_blocked_chat(self):
        api = FakeApi({222: bot.TelegramError(403)})
        self.assertEqual({'eventos': 6, 'enviados': 2, 'pausados': 1, 'pendientes': 0}, self.run_eval(api))
        self.assertEqual([111, 333], [c for c, _ in api.sent])
        self.assertEqual(0, store.suscriptor(self.conn, 222)['activo'])
        self.assertEqual(4, self.conn.execute('SELECT COUNT(*) FROM alertas_enviadas').fetchone()[0])
        again = FakeApi()
        self.assertEqual(0, self.run_eval(again)['eventos'])
        self.assertEqual([], again.sent)

    def test_network_or_rate_limit_leaves_rest_pending(self):
        api = FakeApi({111: bot.TelegramError(429, 5)})
        self.assertEqual(3, self.run_eval(api)['pendientes'])
        self.assertEqual(0, self.conn.execute('SELECT COUNT(*) FROM alertas_enviadas').fetchone()[0])
        self.assertEqual(3, self.run_eval(FakeApi())['enviados'])

    def test_marker_and_watcher(self):
        folder = self.med.parent / 'sync_runtime' / 'scheduler'
        self.assertIsNone(evaluar.marca_sincronizacion(self.med))
        folder.mkdir(parents=True)
        latest = folder / 'last_success.json'
        latest.write_text(json.dumps({'status': 'success', 'finished_at_utc': 'A'}), encoding='utf8')
        llamadas, resumenes = [], [{'pendientes': 2}, {'pendientes': 0}, {'pendientes': 0}]
        vigilante = evaluar.Vigilante(lambda: llamadas.append(1) or resumenes.pop(0),
                                      lambda: evaluar.marca_sincronizacion(self.med))
        vigilante(); vigilante(); vigilante()  # pendiente -> reintenta; luego ya no
        self.assertEqual(2, len(llamadas))
        latest.write_text(json.dumps({'status': 'success', 'finished_at_utc': 'B'}), encoding='utf8')
        vigilante()
        self.assertEqual(3, len(llamadas))

    def test_bot_loop_survives_failing_task(self):
        class Api:
            def __init__(self): self.n = 0
            def call(self, method, **params):
                if method == 'getUpdates': self.n += 1
                return []
        api = Api()
        def falla(): raise RuntimeError('x')
        bot.run(api, None, stop=lambda: api.n >= 2, tarea=falla)
        self.assertEqual(2, api.n)


if __name__ == '__main__':
    unittest.main()
