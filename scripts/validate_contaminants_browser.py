"""Read-only Chrome checks for the pollutant UI on an already running local server.

Requires websocket-client and Chrome. Never starts ingestion or writes a database.
Tests read the real demo API; empty/error cases affect this browser only.
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
    parser.add_argument('--port', type=int, default=5058)
    parser.add_argument('--debug-port', type=int, default=9344)
    parser.add_argument('--chrome', default=r'C:\Program Files\Google\Chrome\Application\chrome.exe')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='aeris-pollutants-browser-') as profile:
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
            call('Network.enable')
            results = []
            def set_value(id, value):
                evaluate(f"document.getElementById({json.dumps(id)}).value={json.dumps(value)};document.getElementById({json.dumps(id)}).dispatchEvent(new Event('change'))")
            def loaded():
                ready("document.getElementById('pollutantChartBox').getAttribute('aria-busy')==='false'")
            def text(id):
                return evaluate(f'document.getElementById({json.dumps(id)}).textContent')
            for width in (1440,390,320):
                call('Emulation.setDeviceMetricsOverride', {'width':width,'height':1000,'deviceScaleFactor':1,'mobile':False})
                call('Emulation.setEmulatedMedia', {'features':[{'name':'prefers-reduced-motion','value':'reduce'}]})
                call('Page.navigate',{'url':f'http://127.0.0.1:{args.port}/inicio/explorar#contaminantes'})
                ready("document.getElementById('pollutantDomain') && !document.getElementById('pollutantDomain').disabled && !document.getElementById('pollutantWorkspace').hidden")
                loaded()
                assert evaluate("document.getElementById('pollutantSource').options.length")==2
                assert evaluate("document.getElementById('airWorkspace').hidden && document.getElementById('weatherWorkspace').hidden")
                set_value('pollutantSource','openaq-archivo');loaded()
                set_value('pollutantStation','openaq:235220');loaded()
                observed={}
                for var in ['pm10','o3','no2','so2','co']:
                    set_value('pollutantVariable',var);loaded()
                    assert text('pollutantCount') not in ('0','\u2014'),(var,text('pollutantStatus'))
                    assert text('pollutantUnit')==('\u00b5g/m\u00b3' if var=='pm10' else 'ppm')
                    label=evaluate("Chart.getChart('pollutantChart').data.datasets[0].label")
                    assert label.startswith('Observaci'),label
                    assert evaluate("Chart.getChart('pollutantChart').data.datasets[0].spanGaps===false")
                    observed[var]=text('pollutantCount')
                set_value('pollutantPeriod','30');loaded()
                assert evaluate("document.getElementById('pollutantRows').children.length")==200
                evaluate("document.getElementById('pollutantMore').click()")
                assert evaluate("document.getElementById('pollutantRows').children.length")==400
                set_value('pollutantStation','openaq:235221');loaded()
                set_value('pollutantVariable','o3');loaded()
                set_value('pollutantPeriod','custom');loaded()
                evaluate("document.getElementById('pollutantFrom').value='2021-09-01';document.getElementById('pollutantTo').value='2021-09-30';document.getElementById('pollutantApply').click()")
                loaded()
                history=text('pollutantCount')
                assert int(history.replace(',',''))>0,(history,text('pollutantStatus'))
                assert '2021-09' in text('pollutantRows')
                set_value('pollutantVariable','pm10');loaded()
                assert text('pollutantCount')=='\u2014'
                assert 'Sin registros' in text('pollutantStatus')
                assert not evaluate("Boolean(Chart.getChart('pollutantChart'))")
                set_value('pollutantPeriod','7');loaded()
                set_value('pollutantSource','open-meteo-cams');loaded()
                set_value('pollutantStation','cams:marques');loaded()
                modeled={}
                for var in ['pm25','pm10']:
                    set_value('pollutantVariable',var);loaded()
                    assert text('pollutantCount') not in ('0','\u2014'),text('pollutantStatus')
                    for id in ['pollutantProduct','pollutantType','pollutantChartKind','pollutantCaption','pollutantTableKind','pollutantSummary']:
                        assert 'Modelo, no medici\u00f3n' in text(id),(id,text(id))
                    assert evaluate("Chart.getChart('pollutantChart').data.datasets[0].borderDash.length")>0
                    assert 'Modelo, no medici\u00f3n' in evaluate("Chart.getChart('pollutantChart').data.datasets[0].label")
                    modeled[var]=text('pollutantCount')
                set_value('pollutantVariable','o3');loaded()
                assert text('pollutantCount')=='\u2014'
                assert 'Modelo, no medici\u00f3n' in text('pollutantStatus')
                set_value('pollutantVariable','pm25');loaded()
                # Rapid changes must not render an old source response as current.
                set_value('pollutantSource','openaq-archivo')
                set_value('pollutantSource','open-meteo-cams');loaded()
                assert 'Modelo, no medici\u00f3n' in evaluate("Chart.getChart('pollutantChart').data.datasets[0].label")
                # Force a transport failure in this browser only; no API or DB changes.
                call('Network.setBlockedURLs',{'urls':['*/api/ambiental/v1/observaciones?*']})
                set_value('pollutantVariable','pm10');loaded()
                assert text('pollutantCount')=='\u2014'
                assert not evaluate("Boolean(Chart.getChart('pollutantChart'))")
                assert evaluate("document.getElementById('pollutantRows').children.length")==0
                call('Network.setBlockedURLs',{'urls':[]})
                evaluate("document.getElementById('pollutantApply').click()");loaded()
                set_value('pollutantPeriod','custom');loaded()
                evaluate("document.getElementById('pollutantFrom').value='2099-01-01';document.getElementById('pollutantTo').value='2099-01-02';document.getElementById('pollutantApply').click()")
                loaded()
                assert text('pollutantCount')=='0',text('pollutantStatus')
                assert 'Sin valores' in text('pollutantChartState')
                assert not evaluate("Boolean(Chart.getChart('pollutantChart'))")
                evaluate("document.getElementById('pollutantFrom').value='2026-10-20';document.getElementById('pollutantTo').value='2021-01-01';document.getElementById('pollutantApply').click()")
                loaded()
                assert text('pollutantCount')=='\u2014'
                # The original views remain independently usable.
                evaluate("document.getElementById('weatherDomain').click()")
                ready("document.getElementById('weatherCharts').getAttribute('aria-busy')==='false'")
                assert evaluate("document.getElementById('weatherSource').options.length")==2
                assert evaluate("document.getElementById('pollutantWorkspace').hidden")
                evaluate("document.querySelector('[data-domain=air]').click()")
                assert not evaluate("document.getElementById('airWorkspace').hidden")
                evaluate("document.getElementById('pollutantDomain').click()");loaded()
                set_value('pollutantPeriod','7');loaded()
                set_value('pollutantStation','cams:marques');loaded()
                set_value('pollutantVariable','pm25');loaded()
                evaluate("document.getElementById('pollutantWorkspace').scrollIntoView();document.getElementById('pollutantSource').focus({preventScroll:true})")
                call('Input.dispatchKeyEvent',{'type':'keyDown','key':'Tab','code':'Tab','windowsVirtualKeyCode':9})
                call('Input.dispatchKeyEvent',{'type':'keyUp','key':'Tab','code':'Tab','windowsVirtualKeyCode':9})
                assert evaluate('document.activeElement.id')=='pollutantMunicipality'
                assert evaluate('document.documentElement.scrollWidth')<=width
                assert not evaluate("performance.getEntriesByType('resource').some(r=>!r.name.startsWith(location.origin))")
                shot=call('Page.captureScreenshot',{'format':'png'})
                (args.output/f'contaminants_{width}.png').write_bytes(base64.b64decode(shot['data']))
                evaluate("document.querySelector('.pollutant-series').scrollIntoView()")
                shot=call('Page.captureScreenshot',{'format':'png'})
                (args.output/f'contaminants_chart_{width}.png').write_bytes(base64.b64decode(shot['data']))
                full=call('Page.getLayoutMetrics')['cssContentSize']
                shot=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':{'x':0,'y':0,'width':width,'height':full['height'],'scale':1}})
                (args.output/f'contaminants_{width}_full.png').write_bytes(base64.b64decode(shot['data']))
                results.append({'width':width,'observed':observed,'cams':modeled,'marques_o3_september2021':history,'overflow':False,'error_and_empty_states':True,'keyboard':True})
            assert not errors,errors
            (args.output/'browser.json').write_text(json.dumps({'results':results,'errors':errors},indent=2),encoding='utf-8')
            print(json.dumps(results));ws.close()
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == '__main__':
    main()
