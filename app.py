"""AERIS — Observatorio de PM2.5. Flask + SQLite (OpenAQ v3).
Instalar: pip install flask
Ejecutar desde la raíz de AERIS: python app.py
Datos: data/aeris_air_quality.db; logo: logo.png o static/logo.png.
"""
from __future__ import annotations
import csv
import io
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from contextlib import closing
from data_ingestion.catalog import read_catalog, SELECTED
from data_ingestion.visibility import connect_readonly
from flask import Flask, Response, jsonify, render_template_string, request, send_file

ROOT = Path(__file__).resolve().parent
app = Flask(__name__)
from aeris_web.config import configure
DB = configure(app, ROOT)

STATIONS = SELECTED

def db_connect():
    if not DB.is_file():
        raise FileNotFoundError('No se encontró la base de datos configurada.')
    con = connect_readonly(DB)
    con.row_factory = sqlite3.Row
    return con

def has_quality(con):
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='calidad_mediciones'").fetchone())

def read_measurements():
    with closing(db_connect()) as con:
        catalog = read_catalog(con)
        quality = has_quality(con)
        join = '''LEFT JOIN calidad_mediciones q ON q.fuente=m.fuente AND q.sensor_id=m.sensor_id
            AND q.fecha_utc=m.fecha_utc AND q.contaminante=m.contaminante''' if quality else ''
        cols = '''COALESCE(q.es_cero,0) AS es_cero, COALESCE(q.es_extremo,0) AS es_extremo,
            COALESCE(q.salto_abrupto,0) AS salto_abrupto, COALESCE(q.requiere_revision,0) AS requiere_revision,
            (q.sensor_id IS NOT NULL) AS quality_evaluated''' if quality else '''0 AS es_cero, 0 AS es_extremo, 0 AS salto_abrupto, 0 AS requiere_revision, 0 AS quality_evaluated'''
        rows = con.execute(f'''SELECT m.fuente,m.sensor_id,m.fecha_utc,m.valor,m.unidad,{cols}
            FROM mediciones m {join} WHERE LOWER(m.contaminante)='pm25' ORDER BY m.fecha_utc''').fetchall()
    result = []
    for r in rows:
        x = dict(r)
        x['sensor_id'] = int(x['sensor_id'])
        x['name'], x['municipality'] = STATIONS.get(x['sensor_id'], (f"Sensor {x['sensor_id']}", 'No identificado'))
        metadata = catalog.get(x['sensor_id'], {}) if x['fuente'] == 'OpenAQ' else {}
        x['name'] = metadata.get('name', x['name'])
        x['municipality'] = metadata.get('municipality', x['municipality'])
        x['lat'], x['lon'] = metadata.get('lat'), metadata.get('lon')
        x['valor'] = float(x['valor'])
        x['year'] = str(x['fecha_utc'])[:4]
        result.append(x)
    return result, quality

def iso_time(s):
    return datetime.fromisoformat(str(s).replace('Z','+00:00')).astimezone(timezone.utc)

def serialize(x):
    result = {k: x[k] for k in ('fuente','sensor_id','name','municipality','fecha_utc','valor','unidad','es_cero','es_extremo','salto_abrupto','requiere_revision','quality_evaluated')}
    if not x['quality_evaluated']:
        for key in ('es_cero','es_extremo','salto_abrupto','requiere_revision'):
            result[key] = None
    return result

def filtered(rows, station='all', period='recent', quality='all'):
    if station != 'all':
        rows = [r for r in rows if str(r['sensor_id']) == station]
    if period == 'recent':
        rows = [r for r in rows if r['year'] == str(datetime.now(timezone.utc).year)]
    elif period == 'historic':
        rows = [r for r in rows if r['year'] != str(datetime.now(timezone.utc).year)]
    elif period in ('7','14','30'):
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=int(period))
        rows = [r for r in rows if cutoff <= iso_time(r['fecha_utc']) <= now]
    if quality == 'exclude':
        rows = [r for r in rows if r['quality_evaluated'] and not r['requiere_revision']]
    elif quality == 'review':
        rows = [r for r in rows if r['requiere_revision']]
    elif quality == 'pending':
        rows = [r for r in rows if not r['quality_evaluated']]
    return rows

def stats(rows):
    if not rows:
        return {'count':0,'mean':None,'minimum':None,'maximum':None,'latest':None,'latest_at':None,'review':0,'zeros':0,'extremes':0,'stations':0,'quality_pending':0}
    values = [r['valor'] for r in rows]
    last = max(rows, key=lambda r:r['fecha_utc'])
    return {'count':len(rows),'mean':round(sum(values)/len(values),2),
        'minimum':round(min(values),2),'maximum':round(max(values),2),
        'latest':round(last['valor'],2),'latest_at':last['fecha_utc'],
        'review':sum(r['requiere_revision'] for r in rows),
        'zeros':sum(r['es_cero'] for r in rows),
        'extremes':sum(r['es_extremo'] for r in rows),
        'stations':len(set(r['sensor_id'] for r in rows)),
        'quality_pending':sum(not r['quality_evaluated'] for r in rows)}

def daily(rows, min_hours=18):
    buckets = defaultdict(list)
    for r in rows:
        buckets[(r['sensor_id'], str(r['fecha_utc'])[:10])].append(r['valor'])
    result = []
    for (sensor, day), vals in sorted(buckets.items(), key=lambda x:(x[0][1],x[0][0])):
        result.append({'sensor_id':sensor,'day':day,'mean':round(sum(vals)/len(vals),2),
                       'count':len(vals),'sufficient':len(vals)>=min_hours})
    return result

def api_error(e):
    if isinstance(e, FileNotFoundError):
        return jsonify({'error':str(e)}), 503
    if isinstance(e, sqlite3.Error):
        return jsonify({'error':'No se pudo leer SQLite. Verifica las tablas mediciones y calidad_mediciones.'}), 503
    raise e

@app.route('/logo.png')
def logo():
    for p in (ROOT/'logo.png', ROOT/'static'/'logo.png', ROOT/'assets'/'logo.png'):
        if p.is_file():
            return send_file(p, mimetype='image/png')
    return Response(status=404)

@app.route('/api/overview')
def overview():
    try:
        rows, qc = read_measurements()
        recent = [r for r in rows if r['year']==str(datetime.now(timezone.utc).year)]
        years = sorted(set(r['year'] for r in rows))
        stations = []
        for sid in sorted(set(r['sensor_id'] for r in rows), key=lambda i:STATIONS.get(i,(str(i),))[0]):
            subset = [r for r in rows if r['sensor_id']==sid]
            latest = max(subset, key=lambda r:r['fecha_utc'])
            name, municipality = STATIONS.get(sid,(f'Sensor {sid}','No identificado'))
            name, municipality = latest['name'], latest['municipality']
            stations.append({'id':sid,'name':name,'municipality':municipality,'count':len(subset),
                'years':sorted(set(r['year'] for r in subset)), 'latest':serialize(latest),
                'review':sum(r['requiere_revision'] for r in subset),
                'quality_pending':sum(not r['quality_evaluated'] for r in subset),
                'lat':latest['lat'], 'lon':latest['lon']})
        return jsonify({'total':stats(rows),'recent':stats(recent),'years':years,
            'quality_available':qc,'stations':stations,'source':'OpenAQ API v3 (datos horarios por sensor)',
            'disclaimer':'OpenAQ es la vía de consulta. El operador y la procedencia primaria de cada sensor requieren verificación documental. No son datos en vivo.'})
    except (FileNotFoundError,sqlite3.Error) as e: return api_error(e)

@app.route('/api/measurements')
def measurements():
    try:
        rows, qc = read_measurements()
        station = request.args.get('station','all')
        period = request.args.get('period','recent')
        quality = request.args.get('quality','all')
        if period not in ('recent','historic','all','7','14','30') or quality not in ('all','exclude','review','pending'):
            return jsonify({'error':'Filtro no válido'}),400
        if station != 'all' and not station.isdigit(): return jsonify({'error':'Estación no válida'}),400
        selected = filtered(rows,station,period,quality)
        points = daily(selected)
        series = defaultdict(list)
        for p in points: series[str(p['sensor_id'])].append(p)
        return jsonify({'stats':stats(selected),'quality_available':qc,
            'series':dict(series),'daily':points,
            'recent_measurements':[serialize(r) for r in sorted(selected,key=lambda x:x['fecha_utc'],reverse=True)[:150]],
            'note':'Promedios diarios calculados por sensor; se distingue si el día tiene al menos 18 registros. Se preservan las mediciones originales.'})
    except (FileNotFoundError,sqlite3.Error) as e: return api_error(e)

@app.route('/api/comparison')
def comparison():
    try:
        rows,_ = read_measurements()
        # Se comparan únicamente las observaciones recientes de 2026 en la intersección temporal.
        recent = [r for r in rows if r['year']==str(datetime.now(timezone.utc).year)]
        sensors = sorted(set(r['sensor_id'] for r in recent))
        if not recent: return jsonify({'stations':[],'period':None})
        starts = {sid:min(iso_time(r['fecha_utc']) for r in recent if r['sensor_id']==sid) for sid in sensors}
        ends = {sid:max(iso_time(r['fecha_utc']) for r in recent if r['sensor_id']==sid) for sid in sensors}
        start, end = max(starts.values()),min(ends.values())
        comparable = [r for r in recent if start<=iso_time(r['fecha_utc'])<=end] if start<=end else []
        result=[]
        for sid in sensors:
            sample=[r for r in comparable if r['sensor_id']==sid]
            s=stats(sample)
            result.append({'id':sid,'name':STATIONS.get(sid,(str(sid),))[0],**s})
        return jsonify({'stations':result,'period':{'from':start.isoformat(),'to':end.isoformat()},
            'note':'Ventana temporal común. Los promedios se calculan sobre las horas efectivamente observadas; la cobertura por estación puede variar.'})
    except (FileNotFoundError,sqlite3.Error) as e: return api_error(e)

@app.route('/api/export.csv')
def export_csv():
    try:
        rows,_=read_measurements()
        period=request.args.get('period','recent'); quality=request.args.get('quality','all'); station=request.args.get('station','all')
        if period not in ('recent','historic','all','7','14','30') or quality not in ('all','exclude','review','pending') or (station!='all' and not station.isdigit()):
            return jsonify({'error':'Filtro no válido'}),400
        data=filtered(rows,station,period,quality)
        buf=io.StringIO(); w=csv.writer(buf)
        w.writerow(['calidad_evaluada','fuente','sensor_id','estacion','municipio','fecha_utc','pm25_ug_m3','es_cero','es_extremo','salto_abrupto','requiere_revision'])
        for r in data:
            w.writerow([r['quality_evaluated'],r['fuente'],r['sensor_id'],r['name'],r['municipality'],r['fecha_utc'],r['valor'],*[r[k] if r['quality_evaluated'] else None for k in ('es_cero','es_extremo','salto_abrupto','requiere_revision')]])
        return Response('\ufeff'+buf.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="AERIS_PM25_OpenAQ.csv"'})
    except (FileNotFoundError,sqlite3.Error) as e: return api_error(e)

@app.route('/health')
def health():
    try:
        rows, quality = read_measurements()
        latest = max((iso_time(r['fecha_utc']) for r in rows), default=None)
        age = (datetime.now(timezone.utc)-latest).total_seconds()/3600 if latest else None
        pending = sum(not r['quality_evaluated'] for r in rows)
        ready = age is not None and 0 <= age <= 48 and quality and pending == 0
        return jsonify({'project':'AERIS','status':'ok' if ready else 'degraded',
                        'database_available':True,'latest_at':latest.isoformat() if latest else None,
                        'age_hours':round(age,2) if age is not None else None,
                        'quality_pending':pending,'quality_available':quality,
                        'freshness_limit_hours':48}), 200 if ready else 503
    except (FileNotFoundError,sqlite3.Error) as e:
        return api_error(e)

@app.route('/')
def index():
    return render_template_string(HTML)

HTML = r'''<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AERIS | Inteligencia ambiental de Querétaro</title>
<link rel="icon" href="/logo.png" type="image/png">
<link rel="stylesheet" href="/static/v2/css/fuentes.css">
<link rel="stylesheet" href="/static/v2/vendor/leaflet/leaflet.css">
<script src="/static/v2/vendor/chartjs/chart.umd.js"></script>
<script src="/static/v2/vendor/leaflet/leaflet.js"></script>
<style>
:root{--bg:#050b16;--panel:#101d30;--panel2:#13253a;--stroke:#25415a;--text:#eaf6ff;--muted:#9db7cb;--cyan:#67e8f9;--green:#5ce4b2;--amber:#ffd078;--red:#ff8794;--blue:#91a4ff}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(circle at 70% -5%,#163455 0,transparent 35%),var(--bg);color:var(--text);font:14px Inter,Arial,sans-serif}a{color:inherit;text-decoration:none}
.layout{display:grid;grid-template-columns:248px minmax(0,1fr);min-height:100vh}aside{position:sticky;top:0;height:100vh;padding:27px 16px;border-right:1px solid var(--stroke);background:#081321}main{min-width:0;max-width:1660px;width:100%;padding:0 34px 48px;margin:auto}
.brand{display:flex;align-items:center;gap:12px;padding:0 10px 26px;border-bottom:1px solid var(--stroke)}.brand img{width:49px;height:49px;object-fit:contain;border-radius:12px}.logo-fallback{display:none;background:linear-gradient(135deg,var(--cyan),var(--blue));color:#081321;border-radius:13px;width:49px;height:49px;place-items:center;font-size:25px;font-weight:900}.brand h1{font-size:25px;letter-spacing:2px;margin:0}.brand small{font-size:9px;color:var(--muted);letter-spacing:1px}.navtitle{margin:30px 10px 12px;color:#7998b1;font-size:10px;letter-spacing:1.6px;font-weight:800}nav a{display:block;padding:14px;border-radius:12px;margin:4px 0;color:var(--muted);font-weight:700}nav a:hover,nav a.active{background:#1b3147;color:var(--cyan)}.sidebar-note{margin:36px 12px;color:var(--muted);font-size:11px;line-height:1.8}
.topbar{min-height:78px;display:flex;align-items:center;justify-content:space-between;gap:12px;border-bottom:1px solid var(--stroke)}.crumb{font-size:10px;color:var(--muted);letter-spacing:1.4px;font-weight:800}.topactions{display:flex;gap:9px;align-items:center;flex-wrap:wrap}.chip{padding:10px 13px;border:1px solid var(--stroke);border-radius:99px;font-size:11px;color:var(--muted);font-weight:700}.btn{cursor:pointer;background:linear-gradient(110deg,#68e4f3,#8e9fff);color:#061222;border:0;border-radius:12px;padding:12px 17px;font-weight:800;font:inherit}.btn.secondary{background:#172b40;color:var(--text);border:1px solid var(--stroke)}.btn:hover{filter:brightness(1.13)}
.hero{margin:26px 0 38px;padding:52px;border:1px solid #284962;border-radius:27px;background:radial-gradient(circle at 86% 33%,#1b4d79,transparent 43%),linear-gradient(120deg,#14283e,#0a1424);position:relative;overflow:hidden}.eyebrow{color:var(--green);font-size:11px;font-weight:800;letter-spacing:1.6px}.hero h2{font-size:clamp(40px,5vw,76px);line-height:1.08;letter-spacing:-3px;margin:25px 0}.hero h2 em{font-style:normal;color:var(--cyan)}.hero p{max-width:700px;color:#bad0e0;line-height:1.9;font-size:15px}.hero-actions{display:flex;gap:12px;margin-top:25px;flex-wrap:wrap}
section{margin:36px 0;scroll-margin-top:20px}.section-head{display:flex;justify-content:space-between;align-items:end;gap:15px;margin-bottom:18px}.section-head h3{font-size:25px;margin:0 0 8px}.section-head p{margin:0;color:var(--muted);line-height:1.6}.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:15px}.card,.panel{background:linear-gradient(145deg,#14263b,#0d1a2b);border:1px solid var(--stroke);border-radius:20px;padding:22px;min-width:0}.card small{display:block;color:var(--muted);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px}.card strong{display:block;font-size:clamp(24px,3vw,37px);margin:14px 0 8px;overflow-wrap:anywhere}.card span{color:var(--muted);font-size:11px;line-height:1.6}.grid2{display:grid;grid-template-columns:1.4fr 1fr;gap:18px}.mapgrid{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(270px,.75fr);gap:17px}#map{height:455px;border-radius:17px;background:#10283d}.maplist{max-height:455px;overflow:auto;display:grid;align-content:start;gap:8px}.station{border:1px solid var(--stroke);border-radius:13px;background:#13263b;padding:13px;cursor:pointer;color:var(--text);text-align:left;font:inherit}.station:hover,.station.selected{border-color:var(--cyan);background:#1b3b52}.station b,.station small{display:block}.station small{margin-top:5px;color:var(--muted);line-height:1.6}.maptip{margin-top:12px;color:var(--muted);font-size:12px;line-height:1.7}
.filters{display:flex;flex-wrap:wrap;gap:12px;margin:15px 0 20px}.filters>div{min-width:175px;flex:1}label{display:block;color:var(--muted);font-size:11px;font-weight:700;margin-bottom:7px}select{width:100%;background:#0c1c2e;border:1px solid #35516a;color:var(--text);padding:12px;border-radius:11px;font:inherit}select:focus{outline:2px solid var(--cyan)}.chartbox{height:350px;position:relative}.chartbox canvas{max-height:100%}.subtle{color:var(--muted);font-size:12px;line-height:1.8}.inline-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:17px 0}.mini{border:1px solid var(--stroke);border-radius:13px;padding:15px;background:#0c1d30}.mini small{display:block;color:var(--muted)}.mini b{display:block;font-size:21px;margin-top:8px}.note{border-left:3px solid var(--cyan);padding:14px 17px;background:#10263a;border-radius:0 12px 12px 0;color:#bed7e8;line-height:1.8}.warn{border-left-color:var(--amber)}.tablewrap{overflow:auto;max-height:460px}table{border-collapse:collapse;width:100%;min-width:760px}th,td{text-align:left;padding:12px;border-bottom:1px solid var(--stroke);font-size:12px}th{color:var(--cyan);position:sticky;top:0;background:#122338}td{color:#c9deed}.tag{display:inline-block;border-radius:7px;padding:5px 8px;background:#183e38;color:var(--green);font-size:10px;font-weight:800}.tag.alert{background:#483421;color:var(--amber)}.footer{color:var(--muted);font-size:11px;text-align:center;padding:35px 0}.error{color:var(--red)}
body.light{--bg:#eef4f9;--panel:#fff;--panel2:#fff;--stroke:#c7d9e7;--text:#142c41;--muted:#527088;background:#eef4f9}body.light aside{background:#e2edf5}body.light .panel,body.light .card,body.light .mini{background:#fff}body.light .hero{background:linear-gradient(120deg,#c9e5f3,#e5edff)}body.light .hero p{color:#38576f}body.light .station{background:#e8f3fb}body.light .station:hover,body.light .station.selected{background:#d3eaf7}body.light select{background:#fff;color:#142c41}body.light .note{background:#e1f1fa;color:#254860}body.light th{background:#d9eaf5}body.light td{color:#25445a}body.light .btn.secondary{background:#e1edf6;color:#18334a}body.light .brand small{color:#456}
@media(max-width:1100px){.layout{grid-template-columns:1fr}aside{position:relative;height:auto;padding:16px}nav{display:flex;overflow:auto}nav a{white-space:nowrap}.sidebar-note,.navtitle{display:none}main{padding:0 19px 35px}.mapgrid,.grid2{grid-template-columns:1fr}.kpis{grid-template-columns:repeat(2,1fr)}}@media(max-width:640px){.hero{padding:28px}.hero h2{letter-spacing:-1.7px}.kpis,.inline-stats{grid-template-columns:1fr}.topbar{flex-wrap:wrap;padding:12px 0}.section-head{display:block}.maplist{max-height:270px}}
</style></head><body>
{% include 'v2/snapshot_notice.html' %}
<div class="layout"><aside><div class="brand"><img id="logo" src="/logo.png" alt="Logo AERIS" onerror="this.style.display='none';document.getElementById('logoFallback').style.display='grid'"><div id="logoFallback" class="logo-fallback">A</div><div><h1>AERIS</h1><small>ENVIRONMENTAL INTELLIGENCE</small></div></div><div class="navtitle">WORKSPACE / EXPLORAR</div><nav><a href="#inicio">⌂ Inicio</a><a href="#indicadores">▤ Indicadores</a><a href="#observatorio">◉ Observatorio</a><a href="#mapa">◎ Mapa interactivo</a><a href="#comparador">▥ Comparador</a><a href="#calidad">◇ Calidad de datos</a><a href="#datos">≡ Mediciones</a><a href="#metodologia">ⓘ Metodología</a></nav><div class="sidebar-note">● DATOS OBSERVADOS · OpenAQ API v3<br>Actualización mediante sincronización local. No transmisión en vivo.</div></aside>
<main><header class="topbar"><div class="crumb">AERIS / PLATAFORMA DE INTELIGENCIA AMBIENTAL</div><div class="topactions"><span class="chip" id="syncChip">● Consultando base local…</span><button class="btn secondary" id="themeBtn">◐ Tema</button><button class="btn secondary" id="presentBtn">⛶ Presentar</button></div></header>
<section class="hero" id="inicio"><div class="eyebrow">● QUERÉTARO · MONITOREO AMBIENTAL DOCUMENTADO</div><h2>Los datos del aire.<br><em>Una nueva perspectiva.</em></h2><p>Explora mediciones horarias observadas de partículas PM2.5, compara estaciones, identifica anomalías y conoce la última lectura disponible. Información obtenida mediante OpenAQ y conservada en una base de datos local con trazabilidad.</p><div class="hero-actions"><a class="btn" href="#observatorio">Explorar mediciones ↗</a><a class="btn secondary" href="#mapa">Ver mapa interactivo →</a><a class="btn secondary" href="#metodologia">Conocer fuentes</a></div></section>
<div class="note warn" id="globalError" style="display:none"></div>
<section id="indicadores"><div class="section-head"><div><h3>Panorama ambiental <span style="color:var(--cyan)">/ a?o actual</span></h3><p>Resumen de observaciones recientes; los registros históricos se muestran por separado.</p></div></div><div class="kpis"><div class="card"><small>Mediciones del a?o actual</small><strong id="kCount">—</strong><span>PM2.5 · observaciones horarias</span></div><div class="card"><small>Estaciones del a?o actual</small><strong id="kStations">—</strong><span>Estaciones con registros disponibles</span></div><div class="card"><small>Promedio observado</small><strong id="kMean">—</strong><span>µg/m³ · sin excluir alertas</span></div><div class="card"><small>Pendientes de revisión</small><strong id="kReview">—</strong><span>Alertas exploratorias de calidad</span></div></div><div class="inline-stats"><div class="mini"><small>Última fecha disponible (UTC)</small><b id="lastDate">—</b></div><div class="mini"><small>Valores cero (todos los periodos)</small><b id="zeroCount">—</b></div><div class="mini"><small>Archivo histórico separado</small><b id="historicCount">—</b></div></div></section>
<section id="mapa"><div class="section-head"><div><h3>Mapa interactivo de Querétaro</h3><p>Explora el territorio con el cursor y selecciona una estación en el panel lateral.</p></div></div><div class="panel"><div class="mapgrid"><div id="map"></div><div><div class="maplist" id="stationList"><p class="subtle">Cargando estaciones…</p></div><div class="maptip" id="mapHint">Las estaciones sin coordenadas verificadas no se colocan como marcadores. El resaltado territorial es una referencia geográfica, no un mapa de concentraciones.</div></div></div></div></section>
<section id="observatorio"><div class="section-head"><div><h3>Observatorio PM2.5</h3><p>Mediciones observadas, evolución temporal y última lectura disponible por sensor.</p></div></div><div class="panel"><div class="filters"><div><label for="stationFilter">Estación</label><select id="stationFilter"><option value="all">Todas las estaciones</option></select></div><div><label for="periodFilter">Periodo</label><select id="periodFilter"><option value="recent">2026 · todo lo disponible</option><option value="7">Últimos 7 días con datos de 2026</option><option value="14">Últimos 14 días con datos de 2026</option><option value="30">Últimos 30 días con datos de 2026</option><option value="historic">Histórico anterior a 2026</option><option value="all">Todos los periodos (sin unir series)</option></select></div><div><label for="qualityFilter">Tratamiento de alertas</label><select id="qualityFilter"><option value="all">Mostrar datos originales</option><option value="exclude">Solo evaluadas sin alerta</option><option value="review">Solo observaciones en revisión</option></select></div><div><label for="chartMode">Visualización</label><select id="chartMode"><option value="line">Líneas</option><option value="bar">Barras</option></select></div></div><div class="inline-stats"><div class="mini"><small>Registros filtrados</small><b id="fCount">—</b></div><div class="mini"><small>Promedio del filtro</small><b id="fMean">—</b></div><div class="mini"><small>Última medición del filtro</small><b id="fLatest">—</b></div></div><div class="chartbox"><canvas id="trendChart"></canvas></div><p class="subtle" id="trendStatus">Cargando datos…</p><div class="note" id="insight">Selecciona una estación para explorar sus mediciones.</div><div class="hero-actions"><button class="btn secondary" id="downloadCSV">↓ Exportar CSV filtrado</button><button class="btn secondary" id="downloadPNG">↓ Exportar gráfica PNG</button></div></div></section>
<section id="comparador"><div class="section-head"><div><h3>Comparador de estaciones</h3><p>Promedios de PM2.5 del a?o actual calculados sobre una ventana temporal compartida.</p></div></div><div class="panel"><div class="chartbox"><canvas id="compareChart"></canvas></div><p class="subtle" id="compareNote">Cargando comparaciones…</p></div></section>
<section id="calidad"><div class="section-head"><div><h3>Auditoría y calidad de datos</h3><p>Reglas de detección reproducibles sin alterar las mediciones originales.</p></div></div><div class="kpis"><div class="card"><small>Total auditado</small><strong id="qcTotal">—</strong><span>Todos los años en SQLite</span></div><div class="card"><small>Valores en cero</small><strong id="qcZero">—</strong><span>Se identifican; no se descartan automáticamente</span></div><div class="card"><small>Extremos &gt; 100</small><strong id="qcExtreme">—</strong><span>Umbral interno exploratorio (µg/m³)</span></div><div class="card"><small>En revisión</small><strong id="qcReview">—</strong><span>Extremos o saltos horarios ≥ 100 µg/m³</span></div></div><div class="note warn" style="margin-top:16px">Una alerta de revisión <b>no confirma un error de medición</b>. La ausencia de alerta tampoco certifica calidad. Los valores originales permanecen intactos. La cobertura y los indicadores se calculan sobre registros disponibles, no sobre una red continua garantizada.</div></section>
<section id="datos"><div class="section-head"><div><h3>Explorador de registros</h3><p>Las 150 observaciones más recientes que cumplen los filtros seleccionados.</p></div></div><div class="panel tablewrap"><table><thead><tr><th>Estación</th><th>Fecha UTC</th><th>PM2.5 (µg/m³)</th><th>Control de calidad</th></tr></thead><tbody id="dataRows"><tr><td colspan="4">Cargando…</td></tr></tbody></table></div></section>
<section id="metodologia"><div class="section-head"><div><h3>Fuentes y metodología</h3><p>Transparencia de procedencia, procesamiento y limitaciones.</p></div></div><div class="grid2"><div class="panel"><h4>Origen de los datos</h4><p class="subtle">Los registros PM2.5 mostrados se recuperaron de <a href="https://openaq.org/" target="_blank" rel="noopener" style="color:var(--cyan)">OpenAQ</a> mediante su API v3 de datos horarios por sensor y se almacenaron en <code>data/aeris_air_quality.db</code>. OpenAQ agrega mediciones procedentes de diversas redes. La identificación del operador primario de cada sensor debe verificarse en los metadatos antes de atribuirlo específicamente a SEMCAC o SINAICA.</p><p class="subtle">Fuentes institucionales para consulta y contraste: <a href="https://sinaica.inecc.gob.mx/" target="_blank" rel="noopener" style="color:var(--cyan)">SINAICA</a> y sistemas locales de monitoreo de Querétaro. Estas referencias no implican que todos los registros del dashboard hayan sido descargados directamente de ellas.</p></div><div class="panel"><h4>Alcance de AERIS</h4><p class="subtle">La fecha de la última observación depende de la sincronización manual o programada del proyecto. No se transmite un flujo en vivo. El sistema ofrece análisis descriptivo, no diagnósticos médicos ni un índice oficial de calidad del aire.</p><p class="subtle">El a?o actual y los dem?s a?os se separan de forma predeterminada. El filtro de alertas permite análisis de sensibilidad sin modificar SQLite. Los promedios diarios requieren al menos 18 registros horarios para considerarse días con cobertura suficiente.</p></div></div></section>
<div class="footer">AERIS · Plataforma de investigación ambiental · Querétaro, México · Mediciones observadas recuperadas vía OpenAQ · Uso exploratorio</div>
</main></div>
<script>
'use strict';
const $=id=>document.getElementById(id);let overview=null,payload=null,trendChart=null,compareChart=null,map=null,markers={},geoLayer=null,loadSeq=0;
const fmt=n=>n===null||n===undefined?'—':Number(n).toLocaleString('es-MX',{maximumFractionDigits:2});
const unit=n=>n===null||n===undefined?'—':fmt(n)+' µg/m³';
const safe=t=>String(t??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function getJSON(url){const r=await fetch(url);let x=await r.json();if(!r.ok)throw Error(x.error||'Error de consulta');return x;}
function showError(err){$('globalError').style.display='block';$('globalError').textContent='No se pudieron cargar los datos: '+err.message;}
function createMap(){if(typeof L==='undefined'){$('mapHint').textContent='El mapa requiere conexión para cargar Leaflet. El selector de estaciones sigue disponible.';return;}
 map=L.map('map',{scrollWheelZoom:false}).setView([20.65,-100.4],9);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors',maxZoom:18}).addTo(map);
 // Capa territorial opcional: se solicita un GeoJSON público. Su ausencia no afecta las mediciones.
 const url='https://raw.githubusercontent.com/angelnmara/geojson/master/mexicoHigh.json';
 fetch(url).then(r=>{if(!r.ok)throw Error('sin mapa');return r.json()}).then(g=>{
   const features=(g.features||[]).filter(f=>/quer[eé]taro/i.test(JSON.stringify(f.properties||{})));
   if(!features.length)return;
   geoLayer=L.geoJSON({type:'FeatureCollection',features},{style:{color:'#67e8f9',weight:2,fillColor:'#1e87a0',fillOpacity:.12},onEachFeature:(f,l)=>{
     l.on('mouseover',()=>{l.setStyle({fillOpacity:.33,weight:4,fillColor:'#55d5ee'});$('mapHint').textContent='Querétaro · Zona geográfica resaltada. Selecciona una estación para ver su última medición.'});
     l.on('mouseout',()=>{geoLayer.resetStyle(l);$('mapHint').textContent='El mapa resalta el territorio; las lecturas pertenecen a estaciones, no a toda la superficie del estado.'});
     l.bindTooltip('Querétaro · Selecciona una estación del panel');
   }}).addTo(map);
   map.fitBounds(geoLayer.getBounds(),{padding:[25,25]});
 }).catch(()=>{$('mapHint').textContent='Mapa base disponible. No se pudo cargar el contorno opcional del estado; las mediciones y el selector funcionan normalmente.'});
}
function pickStation(id){$('stationFilter').value=String(id);document.querySelectorAll('.station').forEach(x=>x.classList.toggle('selected',x.dataset.id===String(id)));if(markers[id]){map.flyTo(markers[id].getLatLng(),12,{duration:.8});markers[id].openPopup()}loadData();document.querySelector('#observatorio').scrollIntoView({behavior:'smooth'});}
function populateStations(){const select=$('stationFilter');$('stationList').innerHTML='';for(const s of overview.stations){const o=document.createElement('option');o.value=s.id;o.textContent=s.name+' · '+s.years.join(', ');select.appendChild(o);
 const b=document.createElement('button');b.className='station';b.dataset.id=s.id;b.innerHTML='<b>'+safe(s.name)+'</b><small>'+safe(s.municipality)+' · '+fmt(s.count)+' registros · '+safe(s.years.join(', '))+'</small><small>Última lectura: '+unit(s.latest.valor)+' · '+safe(s.latest.fecha_utc)+'</small>';
 b.onclick=()=>pickStation(s.id);$('stationList').appendChild(b);
 if(map&&s.lat!==null&&s.lon!==null){const marker=L.circleMarker([s.lat,s.lon],{radius:10,color:'#67e8f9',fillColor:'#3587ff',fillOpacity:.85,weight:3}).addTo(map);marker.bindPopup('<b>'+safe(s.name)+'</b><p>Última lectura: '+unit(s.latest.valor)+'</p><small>'+safe(s.latest.fecha_utc)+'</small>');marker.on('click',()=>pickStation(s.id));markers[s.id]=marker;}
}}
async function loadOverview(){overview=await getJSON('/api/overview');$('globalError').style.display='none';const r=overview.recent,t=overview.total;
 $('kCount').textContent=fmt(r.count);$('kStations').textContent=fmt(r.stations);$('kMean').textContent=unit(r.mean);$('kReview').textContent=fmt(r.review);
 $('lastDate').textContent=r.latest_at?r.latest_at.replace('T',' ').replace('Z',' UTC'):'—';$('zeroCount').textContent=fmt(t.zeros);$('historicCount').textContent=fmt(t.count-r.count);
 $('qcTotal').textContent=fmt(t.count);$('qcZero').textContent=fmt(t.zeros);$('qcExtreme').textContent=fmt(t.extremes);$('qcReview').textContent=fmt(t.review);
 $('syncChip').textContent='● Último registro: '+(r.latest_at||'sin datos');
 if(overview.total.quality_pending){$('globalError').style.display='block';$('globalError').textContent=fmt(overview.total.quality_pending)+' observaciones pendientes de evaluar. El filtro de evaluadas sin alerta las excluye.';}
 if(!overview.quality_available){$('qcReview').textContent='N/D';$('kReview').textContent='N/D';$('globalError').style.display='block';$('globalError').textContent='La tabla calidad_mediciones no existe: los indicadores de control de calidad aún no están disponibles.';}
 populateStations();await Promise.all([loadData(),loadComparison()]);}
function filters(){return {station:$('stationFilter').value,period:$('periodFilter').value,quality:$('qualityFilter').value};}
async function loadData(){const seq=++loadSeq;const q=new URLSearchParams(filters());$('trendStatus').textContent='Consultando mediciones…';try{const d=await getJSON('/api/measurements?'+q);if(seq!==loadSeq)return;payload=d;
 $('fCount').textContent=fmt(d.stats.count);$('fMean').textContent=unit(d.stats.mean);$('fLatest').textContent=unit(d.stats.latest);
 $('trendStatus').textContent='Última lectura: '+(d.stats.latest_at||'sin datos')+' UTC · '+d.stats.stations+' estaciones · '+d.stats.review+' observaciones en revisión';
 $('insight').textContent='Los puntos de la gráfica son promedios diarios por estación. Los días con menos de 18 registros se representan como interrupciones. Los datos marcados no se eliminan de la base original.';
 drawTrend();renderRows(d.recent_measurements);
 }catch(e){if(seq!==loadSeq)return;$('trendStatus').textContent='Error: '+e.message;showError(e);}}
function drawTrend(){if(trendChart)trendChart.destroy();if(!payload)return;const good=payload.daily.filter(x=>x.sufficient);const days=[...new Set(payload.daily.map(x=>x.day))].sort();const ids=[...new Set(good.map(x=>x.sensor_id))];const colors=['#67e8f9','#91a4ff','#5ce4b2','#ffd078','#ff8794','#d1a6ff','#76a8ef'];
 const datasets=ids.map((id,i)=>{const lookup=new Map(good.filter(x=>x.sensor_id===id).map(x=>[x.day,x.mean]));const s=overview.stations.find(x=>x.id===id);return {label:s?s.name:String(id),data:days.map(day=>lookup.has(day)?lookup.get(day):null),borderColor:colors[i%colors.length],backgroundColor:colors[i%colors.length]+'55',borderWidth:2,spanGaps:false,tension:.25,pointRadius:2};});
 trendChart=new Chart($('trendChart'),{type:$('chartMode').value,data:{labels:days,datasets},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{position:'bottom',labels:{color:'#a9c4d8'}},tooltip:{callbacks:{label:c=>c.dataset.label+': '+unit(c.parsed.y)}}},scales:{x:{ticks:{color:'#9db7cb',maxTicksLimit:9}},y:{beginAtZero:true,ticks:{color:'#9db7cb'},title:{display:true,text:'PM2.5 (µg/m³)',color:'#9db7cb'}}}}});
 if(!days.length)$('trendStatus').textContent+=' · No hay días con al menos 18 registros para el filtro actual.';}
function renderRows(rows){$('dataRows').innerHTML=rows.length?rows.map(r=>'<tr><td>'+safe(r.name)+'</td><td>'+safe(r.fecha_utc)+'</td><td>'+fmt(r.valor)+'</td><td><span class="tag '+(r.requiere_revision?'alert':'')+'">'+(r.requiere_revision?'Revisión pendiente':'Sin alerta')+'</span></td></tr>').join(''):'<tr><td colspan="4">No hay registros para los filtros actuales.</td></tr>';}
async function loadComparison(){try{const d=await getJSON('/api/comparison');if(compareChart)compareChart.destroy();compareChart=new Chart($('compareChart'),{type:'bar',data:{labels:d.stations.map(x=>x.name),datasets:[{data:d.stations.map(x=>x.mean),label:'PM2.5 promedio (µg/m³)',backgroundColor:['#67e8f9','#91a4ff','#5ce4b2','#ffd078','#ff8794'],borderRadius:8}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#a9c4d8'}},y:{beginAtZero:true,ticks:{color:'#a9c4d8'}}}}});
 $('compareNote').textContent=d.period?'Ventana común UTC: '+d.period.from+' a '+d.period.to+'. Cobertura horaria variable entre estaciones; no se han imputado horas faltantes.':'No hay estaciones recientes comparables.';
 }catch(e){$('compareNote').textContent='No se pudo calcular la comparación: '+e.message;}}
for(const id of ['stationFilter','periodFilter','qualityFilter'])$(id).addEventListener('change',loadData);$('chartMode').addEventListener('change',drawTrend);
$('downloadCSV').onclick=()=>{location.href='/api/export.csv?'+new URLSearchParams(filters());};$('downloadPNG').onclick=()=>{if(!trendChart)return;const a=document.createElement('a');a.href=trendChart.toBase64Image();a.download='AERIS_PM25_grafica.png';a.click()};
$('themeBtn').onclick=()=>document.body.classList.toggle('light');$('presentBtn').onclick=()=>{const a=document.querySelector('aside');a.style.display=a.style.display==='none'?'':'none';document.querySelector('.layout').style.gridTemplateColumns=a.style.display==='none'?'1fr':'';if(map)setTimeout(()=>map.invalidateSize(),250)};
const observer=new IntersectionObserver(entries=>{const active=entries.find(e=>e.isIntersecting);if(active)document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('active',a.getAttribute('href')==='#'+active.target.id))},{rootMargin:'-15% 0px -70% 0px'});document.querySelectorAll('main section[id]').forEach(x=>observer.observe(x));
createMap();loadOverview().catch(showError);
</script></body></html>'''

from aeris_web import register_v2
register_v2(app, lambda: DB)
# Capa ambiental: misma base salvo que AERIS_AMBIENTAL_DB_PATH indique otra (solo local;
# la beta sirve exclusivamente la instantánea verificada).
from aeris_web.ambiental import register_ambiental
AMBIENTAL_DB = Path(os.environ['AERIS_AMBIENTAL_DB_PATH']) if (
    os.environ.get('AERIS_AMBIENTAL_DB_PATH') and app.config['AERIS_ENV'] == 'local') else DB
register_ambiental(app, lambda: AMBIENTAL_DB)

if __name__ == '__main__':
    app.run(host='127.0.0.1',port=int(os.environ.get('PORT','5000')),debug=False)
