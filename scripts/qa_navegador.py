"""QA de navegador de solo lectura: capturas y errores de JavaScript/red por ruta y ancho.

Usa Chrome sin interfaz vía CDP contra un servidor local ya iniciado. No escribe en ninguna base.
"""
import argparse
import base64
import json
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

import websocket

CHROME = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
ANCHOS = {'escritorio': (1440, 900, False), 'movil': (390, 844, True)}


class Navegador:
    def __init__(self, puerto=9241):
        self.perfil = tempfile.TemporaryDirectory(prefix='aeris-qa-')
        self.proceso = subprocess.Popen(
            [str(CHROME), '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
             '--disable-background-networking', '--disable-extensions', '--hide-scrollbars',
             f'--remote-debugging-port={puerto}', f'--remote-allow-origins=http://127.0.0.1:{puerto}',
             '--user-data-dir=' + self.perfil.name, 'about:blank'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        limite = time.monotonic() + 20
        while True:
            try:
                with urlopen(f'http://127.0.0.1:{puerto}/json/list', timeout=2) as r:
                    destino = next(t for t in json.load(r) if t['type'] == 'page')
                break
            except Exception:
                if time.monotonic() > limite:
                    raise
                time.sleep(.2)
        self.ws = websocket.create_connection(destino['webSocketDebuggerUrl'],
                                              origin=f'http://127.0.0.1:{puerto}', timeout=30)
        self.n = 0
        self.eventos = []
        for dominio in ('Page', 'Runtime', 'Network', 'Log'):
            self.cmd(dominio + '.enable')

    def cmd(self, metodo, params=None):
        self.n += 1
        esperado = self.n
        self.ws.send(json.dumps({'id': esperado, 'method': metodo, 'params': params or {}}))
        while True:
            m = json.loads(self.ws.recv())
            if 'method' in m:
                self.eventos.append(m)
            if m.get('id') == esperado:
                if 'error' in m:
                    raise RuntimeError(str(m['error']))
                return m.get('result', {})

    def evaluar(self, expresion):
        r = self.cmd('Runtime.evaluate', {'expression': expresion, 'returnByValue': True, 'awaitPromise': True})
        return r.get('result', {}).get('value')

    def drenar(self, segundos):
        fin = time.monotonic() + segundos
        self.ws.settimeout(.2)
        while time.monotonic() < fin:
            try:
                self.eventos.append(json.loads(self.ws.recv()))
            except websocket.WebSocketTimeoutException:
                pass
        self.ws.settimeout(30)

    def cerrar(self):
        try:
            self.ws.close()
        finally:
            self.proceso.terminate()
            self.proceso.wait(10)
            self.perfil.cleanup()


def problemas(eventos):
    salida = []
    for e in eventos:
        m, p = e.get('method'), e.get('params', {})
        if m == 'Runtime.exceptionThrown':
            d = p['exceptionDetails']
            salida.append('JS: ' + (d.get('exception', {}).get('description') or d.get('text', ''))[:300])
        elif m == 'Runtime.consoleAPICalled' and p.get('type') in ('error', 'warning'):
            salida.append('consola.' + p['type'] + ': ' + ' '.join(str(a.get('value', a.get('description', ''))) for a in p['args'])[:300])
        elif m == 'Log.entryAdded' and p['entry']['level'] in ('error', 'warning'):
            salida.append('log: ' + p['entry']['text'][:300] + ' ' + p['entry'].get('url', ''))
        elif m == 'Network.loadingFailed' and not p.get('canceled'):
            salida.append('red: ' + p.get('errorText', '') + ' ' + p.get('requestId', ''))
        elif m == 'Network.responseReceived' and p['response']['status'] >= 400:
            salida.append(f"HTTP {p['response']['status']}: {p['response']['url']}")
    return salida


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:5051')
    parser.add_argument('--ruta', action='append', required=True)
    parser.add_argument('--salida', type=Path, required=True)
    parser.add_argument('--espera', type=float, default=3.0)
    parser.add_argument('--ancho', action='append', choices=list(ANCHOS))
    parser.add_argument('--accion', action='append', default=[], help='ruta=expresiónJS ejecutada antes de capturar')
    args = parser.parse_args(argv)
    args.salida.mkdir(parents=True, exist_ok=True)
    acciones = {}
    for a in args.accion:
        ruta, expresion = a.split('=', 1)
        acciones.setdefault(ruta, []).append(expresion)
    informe = {}
    nav = Navegador()
    try:
        for nombre in args.ancho or list(ANCHOS):
            ancho, alto, movil = ANCHOS[nombre]
            nav.cmd('Emulation.setDeviceMetricsOverride', {'width': ancho, 'height': alto, 'deviceScaleFactor': 1, 'mobile': movil})
            for ruta in args.ruta:
                # Página en blanco entre rutas: un cambio de solo #hash también recarga.
                nav.cmd('Page.navigate', {'url': 'about:blank'})
                nav.drenar(.3)
                nav.eventos.clear()
                nav.cmd('Page.navigate', {'url': args.base + ruta})
                nav.drenar(args.espera)
                for expresion in acciones.get(ruta, []):
                    nav.evaluar(expresion)
                    nav.drenar(args.espera)
                # Recorre la página para disparar contenido diferido y animaciones de entrada.
                altura = nav.evaluar('document.documentElement.scrollHeight') or alto
                for y in range(0, int(altura), alto):
                    nav.evaluar(f'window.scrollTo(0,{y})')
                    nav.drenar(.25)
                nav.evaluar('window.scrollTo(0,0)')
                nav.drenar(.6)
                altura = nav.evaluar('document.documentElement.scrollHeight') or alto
                desborde = nav.evaluar('document.documentElement.scrollWidth > window.innerWidth + 1')
                captura = nav.cmd('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': True,
                                  'clip': {'x': 0, 'y': 0, 'width': ancho, 'height': min(altura, 16000), 'scale': 1}})
                limpio = ''.join(c if c.isalnum() or c in '-_' else '_' for c in ruta.strip('/')) or 'raiz'
                archivo = args.salida / f'{limpio}_{nombre}.png'
                archivo.write_bytes(base64.b64decode(captura['data']))
                informe[f'{ruta} [{nombre}]'] = {'captura': str(archivo), 'altura': altura,
                                                 'desborde_horizontal': desborde, 'problemas': problemas(nav.eventos)}
    finally:
        nav.cerrar()
    (args.salida / 'informe.json').write_text(json.dumps(informe, indent=2, ensure_ascii=False), encoding='utf-8')
    for clave, valor in informe.items():
        print(clave, 'altura', valor['altura'], 'desborde', valor['desborde_horizontal'], 'problemas', len(valor['problemas']))
        for p in valor['problemas'][:8]:
            print('   ', p)


if __name__ == '__main__':
    main()
