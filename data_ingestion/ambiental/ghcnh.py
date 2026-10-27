"""Conector NOAA GHCNh: METAR FM-15/FM-16 de estaciones del catálogo, fechas UTC explícitas.

Contrato verificado en ghcnh_DOCUMENTATION.pdf v1.1.0 (10/03/2026):
- DATE y Year..Minute están en UTC; los valores son instantáneos del reporte, no promedios.
- Códigos de calidad: letras a-z (QC integrado de GHCNh), 2/3/6/7 heredados (sospechoso/erróneo),
  U/P/I/M/R (valor editado o insertado) y o/f en humedad derivada => marca_origen=1.
  Un código vacío significa «sin marca», no «validado».
- Precipitación METAR es un total acumulado dentro de la hora; se excluye hasta implementar
  la regla del último reporte de cada hora con su propio periodo.
"""
import csv
import io
from datetime import datetime, timezone

URL = 'https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/access/by-year/{anio}/psv/GHCNh_{estacion}_{anio}.psv'
FUENTE = 'noaa-ghcnh'
REPORTES = {'FM15': 'FM-15', 'FM16': 'FM-16'}
COLUMNAS = {
    'temperature': ('temperatura_aire', '°C'),
    'dew_point_temperature': ('punto_rocio', '°C'),
    'relative_humidity': ('humedad_relativa', '%'),
    'wind_speed': ('viento_velocidad', 'm/s'),
    'wind_direction': ('viento_direccion', '°'),
    'wind_gust': ('viento_rafaga', 'm/s'),
    'altimeter': ('presion_altimetro', 'hPa'),
    'sea_level_pressure': ('presion_nivel_mar', 'hPa'),
    'station_level_pressure': ('presion_superficie', 'hPa'),
    'visibility': ('visibilidad', 'km'),
}
MARCAS = set('abcdefhiklmnoprstuvwxz') | set('2367UPIMR')


def marcado(codigo):
    return any(c in MARCAS for c in codigo)


def instante(fila):
    fecha = datetime.fromisoformat(fila['DATE'])
    if fecha.tzinfo is not None:
        raise ValueError('GHCNh no declara zona en DATE; se esperaba UTC implícito documentado')
    partes = tuple(int(fila[k]) for k in ('Year', 'Month', 'Day', 'Hour', 'Minute'))
    if partes != (fecha.year, fecha.month, fecha.day, fecha.hour, fecha.minute):
        raise ValueError('DATE no coincide con Year..Minute')
    return fecha.replace(tzinfo=timezone.utc)


def interpretar(texto, estacion_externa, estacion_id, desde=None, hasta=None):
    """Devuelve (registros, resumen). Falla cerrado si cambia el esquema del archivo."""
    lector = csv.DictReader(io.StringIO(texto), delimiter='|')
    faltantes = {'STATION', 'DATE', 'Year', 'Month', 'Day', 'Hour', 'Minute'} | {
        f'{c}{s}' for c in COLUMNAS for s in ('', '_Measurement_Code', '_Quality_Code', '_Report_Type')}
    faltantes -= set(lector.fieldnames or ())
    if faltantes:
        raise ValueError(f'Esquema GHCNh inesperado; faltan columnas: {sorted(faltantes)[:5]}')
    registros, excluidos, filas = [], {}, 0
    for fila in lector:
        filas += 1
        if fila['STATION'] != estacion_externa:
            raise ValueError('El archivo contiene otra estación')
        fecha = instante(fila)
        if (desde and fecha < desde) or (hasta and fecha >= hasta):
            continue
        for columna, (variable, unidad) in COLUMNAS.items():
            texto_valor = fila[columna].strip()
            if not texto_valor:
                continue
            tipo = fila[columna + '_Report_Type'].strip()
            if tipo not in REPORTES:
                excluidos[tipo or 'sin_tipo'] = excluidos.get(tipo or 'sin_tipo', 0) + 1
                continue
            medicion = fila[columna + '_Measurement_Code'].strip()
            calidad = fila[columna + '_Quality_Code'].strip()
            valor = float(texto_valor)
            if columna == 'wind_direction' and valor == 999:
                if medicion != 'C':
                    excluidos['direccion_999_no_calma'] = excluidos.get('direccion_999_no_calma', 0) + 1
                    continue
                valor = 0.0  # Documentación: dirección 000 representa calma.
            registros.append({
                'estacion_id': estacion_id, 'variable_id': variable, 'fecha': fecha,
                'valor': valor, 'valor_original': texto_valor, 'unidad_original': unidad,
                'periodo': 'instantaneo', 'tipo_reporte': REPORTES[tipo],
                'codigo_medicion': medicion, 'calidad_origen': calidad, 'marca_origen': marcado(calidad),
            })
    return registros, {'filas_archivo': filas, 'valores_metar': len(registros), 'valores_excluidos': excluidos}
