"""Read-only Chrome checks for the educational UI on an already running local server.

Requires websocket-client and Chrome. Never starts ingestion or writes a database.
All numeric test inputs belong to the labelled simulator, never to a measurement.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request

import websocket


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=5056)
    parser.add_argument('--debug-port', type=int, default=9342)
    parser.add_argument('--chrome', default=r'C:\Program Files\Google\Chrome\Application\chrome.exe')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='aeris-aprende-browser-') as profile:
        process = subprocess.Popen([args.chrome, '--headless=new', '--disable-gpu', '--no-first-run',
                                    '--disable-background-networking', '--no-default-browser-check',
                                    '--remote-debugging-address=127.0.0.1',
                                    '--remote-debugging-port=' + str(args.debug_port),
                                    '--user-data-dir=' + profile, 'about:blank'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{args.debug_port}/json', timeout=1) as response:
                        pages = json.load(response)
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError('Chrome debugging unavailable')
            ws = websocket.create_connection(next(p['webSocketDebuggerUrl'] for p in pages if p['type'] == 'page'),
                                             suppress_origin=True, timeout=30)
            sequence = 0
            errors = []

            def call(method, params=None):
                nonlocal sequence
                sequence += 1
                target = sequence
                ws.send(json.dumps({'id': target, 'method': method, 'params': params or {}}))
                while True:
                    message = json.loads(ws.recv())
                    if message.get('method') == 'Runtime.exceptionThrown':
                        errors.append(message)
                    if message.get('id') == target:
                        if 'error' in message:
                            raise RuntimeError(message['error'])
                        return message.get('result', {})

            def evaluate(expression):
                result = call('Runtime.evaluate', {'expression': expression, 'returnByValue': True})
                if result.get('exceptionDetails'):
                    raise RuntimeError(result['exceptionDetails'])
                return result['result'].get('value')

            def ready(expression):
                for _ in range(240):
                    if evaluate(expression):
                        return
                    time.sleep(.1)
                raise AssertionError('Timed out: ' + expression)

            call('Page.enable')
            call('Runtime.enable')
            results = []
            cases = [('pm25', '15.5', 16, 'Aceptable'), ('pm10', '50.5', 51, 'Mala'),
                     ('o3', '0.0585', .059, 'Aceptable'), ('no2', '0.1065', .107, 'Mala'),
                     ('so2', '0.3045', .305, 'Extremadamente mala'), ('co', '5.005', 5.01, 'Aceptable')]
            for width in (1440, 390, 320):
                call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 960, 'deviceScaleFactor': 1, 'mobile': False})
                call('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-reduced-motion', 'value': 'reduce'}]})
                call('Page.navigate', {'url': f'http://127.0.0.1:{args.port}/inicio/aprende'})
                ready('Boolean(window.AerisAprende)')
                for key, raw, expected, band in cases:
                    actual = evaluate(f'AerisAprende.classify({json.dumps(key)}, {json.dumps(raw)})')
                    assert actual['value'] == expected and actual['band']['nombre'] == band, actual
                    evaluate(f"document.getElementById('apContaminante').value={json.dumps(key)};document.getElementById('apContaminante').dispatchEvent(new Event('change'))")
                    assert evaluate("document.getElementById('apEntrada').value") == '0'
                    evaluate(f"document.getElementById('apEntrada').value={json.dumps(raw)};document.getElementById('apEntrada').dispatchEvent(new Event('input'))")
                    assert evaluate("document.getElementById('apCategoria').textContent") == band
                    assert evaluate("document.getElementById('apTablaBandas').rows.length") == 5
                    assert evaluate("document.getElementById('apOms').hidden") == (key != 'pm25')
                for raw in ('', '-1', 'NaN', 'Infinity', '1e999', '1,234.5'):
                    assert evaluate(f'AerisAprende.classify("co", {json.dumps(raw)})') is None
                assert evaluate('AerisAprende.classify("co", "5,005").value') == 5.01
                assert evaluate('AerisAprende.classify("pm25", "0").value') == 0
                assert evaluate('AerisAprende.classify("pm25", "1000").band.nombre') == 'Extremadamente mala'
                # Every half-way case across every band boundary matches Python's existing definition.
                from aeris_web.indice import CONTAMINANTES, banda
                from decimal import Decimal
                for key, (_, _, decimals, limits, _) in CONTAMINANTES.items():
                    step = Decimal(1).scaleb(-decimals)
                    for limit in limits:
                        for offset in (Decimal('0'), Decimal('.4'), Decimal('.5'), Decimal('1')):
                            raw = str(Decimal(str(limit)) + step * offset)
                            expected_band, expected_value = banda(key, float(raw))
                            actual = evaluate(f'AerisAprende.classify({json.dumps(key)}, {json.dumps(raw)})')
                            assert (actual['band']['nombre'], actual['value']) == (expected_band, expected_value)
                evaluate("document.getElementById('apContaminante').value='o3';document.getElementById('apContaminante').dispatchEvent(new Event('change'));document.getElementById('apEntrada').value='0.0905';document.getElementById('apEntrada').dispatchEvent(new Event('input'));document.querySelector('.ap-simulador').scrollIntoView()")
                assert evaluate("document.getElementById('apUnidad').textContent") == 'ppm'
                assert 'máximo horario' in evaluate("document.getElementById('apMetodo').textContent")
                evaluate("document.getElementById('apContaminante').focus()")
                call('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'Tab', 'code': 'Tab', 'windowsVirtualKeyCode': 9})
                call('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'Tab', 'code': 'Tab', 'windowsVirtualKeyCode': 9})
                assert evaluate('document.activeElement.id') == 'apEntrada'
                size = evaluate('({width:innerWidth, scroll:document.documentElement.scrollWidth})')
                assert size['scroll'] <= width, size
                assert not evaluate("performance.getEntriesByType('resource').some(r=>!r.name.startsWith(location.origin))")
                time.sleep(.2)
                shot = call('Page.captureScreenshot', {'format': 'png'})
                (args.output / f'aprende_{width}.png').write_bytes(base64.b64decode(shot['data']))
                full = call('Page.getLayoutMetrics')['cssContentSize']
                shot = call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': True,
                            'clip': {'x': 0, 'y': 0, 'width': width, 'height': full['height'], 'scale': 1}})
                (args.output / f'aprende_{width}_full.png').write_bytes(base64.b64decode(shot['data']))
                results.append({'width': width, 'horizontal_overflow': False, 'boundary_checks': 96, 'keyboard': True})
            assert not errors, errors
            (args.output / 'browser.json').write_text(json.dumps({'results': results, 'errors': errors}, indent=2), encoding='utf-8')
            print(json.dumps(results))
            ws.close()
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == '__main__':
    # Executed as a script, the project root must precede installed packages.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
