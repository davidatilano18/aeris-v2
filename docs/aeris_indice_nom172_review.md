# Revisión independiente de indice.py · 20/10/2026

Objeto revisado: `aeris_web/indice.py` del commit
`7e8ef44c2f0124a1046dc15ab74bceaa1e82365f`. **No se editó ese archivo.**
Es una revisión del cálculo y sus límites; no una certificación regulatoria o sanitaria.

## Referencia oficial y coincidencias

Se consultó la [NOM-172-SEMARNAT-2023 publicada el 25/01/2024](https://sidof.segob.gob.mx/notas/docFuente/5715154)
y su [PDF alojado por la Secretaría de Economía](https://platiica.economia.gob.mx/wp-content/uploads/sites/2/PDF_Normas_Publicas/nom-172-semarnat-2023.pdf).
Tablas 2–9 y apartados 5.2.4–5.2.5:

| Contaminante | Unidad | Decimales | Topes Buena / Aceptable / Mala / Muy mala, referencia 2026 | Método diario |
|---|---|---:|---|---|
| PM2.5 | µg/m³ | 0 | 15 / 25 / 79 / 130 | Promedio 24 h |
| PM10 | µg/m³ | 0 | 45 / 50 / 132 / 213 | Promedio 24 h |
| O₃ | ppm | 3 | .058 / .090 / .135 / .175 | Máximo horario |
| NO₂ | ppm | 3 | .053 / .106 / .160 / .213 | Máximo horario |
| SO₂ | ppm | 3 | .035 / .075 / .185 / .304 | Máximo horario |
| CO | ppm | 2 | 5 / 9 / 12 / 16 | Máximo móvil 8 h |

Coinciden con `CONTAMINANTES`. El PDF confirma **≤** en el tope de Buena y
**µg/m³** para partículas: la extracción HTML pierde trazos de estos símbolos.
No se tomó esa pérdida tipográfica como discrepancia del código.

La regla decimal es mitad hacia arriba. Cada ventana de CO exige seis horas e
incluye la hora de cierre y las siete anteriores. Partículas: 18 horas por día
desde las 00:00. El cálculo horario de partículas es otro método: NowCast ponderado
de 12 h, con dos de las tres horas recientes. `indice.py` implementa el reporte diario.

## Hallazgos del código, pendientes para Claude

### A. Precisión antes del redondeo · defecto reproducido

`redondear()` aplica correctamente `ROUND_HALF_UP` al argumento recibido, pero
`concentracion_diaria()` promedia en binario antes de convertir el resultado a Decimal.
Se reprodujo una diferencia con el promedio decimal exacto:

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from aeris_web.indice import concentracion_diaria, banda

t = datetime(2026, 1, 1, tzinfo=ZoneInfo('America/Mexico_City'))
# Entrada de prueba aritmética, NO observaciones ambientales ni registros insertados.
valores = [25.455] * 18 + [26.31]
horas = {t + timedelta(hours=i): v for i, v in enumerate(valores)}
base = concentracion_diaria('pm25', horas)
print(repr(base), banda('pm25', base))
```

Resultado en el Python local: `25.499999999999996 ('Aceptable', 25.0)`.
La suma decimal exacta es 484.5; dividida entre 19 da **25.5**, que redondea a **26**
y corresponde a **Mala**. No se ha comprobado que una observación real del corte
esté afectada; el caso demuestra vulnerabilidad numérica, no contaminación medida.

Propuesta: conservar precisión decimal al agregar y probar promedios/ventanas en
empates antes de cambiar el backend. No corregir mediante un epsilon arbitrario.
El nuevo simulador opera sobre la cadena decimal introducida y no reproduce este defecto.

### B. gases-v1 · efecto de selección que requiere revisión científica

`requiere_revision()` elimina del cálculo toda hora que supere el último tope y
ciertos saltos entre horas adyacentes. Esas exclusiones son una política de AERIS,
no las bandas mismas ni una confirmación de invalidez instrumental.
Por construcción, quitar todos los valores superiores al tope de Muy mala puede
impedir observar la banda Extrema para gases/PM10 y reducir máximos y coberturas.
No debe interpretarse su ausencia posterior como ausencia de episodios extremos.

Propuesta: revisar con Claude evidencia del proveedor, sensibilidad del resumen con
y sin exclusiones y disponibilidad de validación manual/versionada. No se alteró
la política ni se reincorporaron horas. La interfaz explica su carácter automático.

### C. Mínimo diario adicional de gases/CO · diferencia deliberada

El código impone `HORAS_MINIMAS=18` antes del máximo diario de gases y también antes
del máximo móvil de CO. Esa restricción adicional ya está comentada en el módulo.
Puede retirar días que sí tengan alguna ventana de CO calculable. El frontend
ahora la identifica como criterio propio, sin atribuirla a una exigencia universal
del apartado 5.2.5.4.

### D. Alcance histórico y representatividad · límites, no umbrales nuevos

El módulo usa bandas de referencia 2026 para todos los años y omite 2021 del resumen
principal (`DESDE_ANIO=2023`), aunque conserva observaciones de 2021 en el dataset.
Las comparaciones no equivalen al cumplimiento de la regulación vigente en cada año.
`resumen_por_anio`/`_resumir` cuentan combinaciones estación-día disponibles, con
distinta cobertura por contaminante. No demuestran una tendencia estatal ni que
una variable sea causalmente responsable de un deterioro.

Los registros horarios recibidos no permiten verificar aquí los minutos de captura
necesarios para formar cada promedio horario. La suficiencia del agregador no
certifica los instrumentos ni la validación oficial del dato de origen.

## Comprobaciones y conclusión

- Umbrales, unidades, métodos y precisión cotejados independientemente; cinco
  pruebas frontend adicionales y 96 casos de frontera por ancho en Chrome.
- `maximo_movil_8h` recorre las 24 horas de cierre del día, admite huecos con mínimo
  de seis y consulta horas anteriores, sin rellenarlas. Los filtros gases-v1 solo
  comparan con la hora previa adyacente; no miran al futuro.
- El selector y las tablas reutilizan la configuración existente; no cambian el índice.

**Apto como material educativo sobre la configuración publicada; no declarar
conformidad integral del backend con la NOM.** Entregar los hallazgos A–D a Claude
antes de usar el resumen como prueba de cumplimiento o de ausencia de episodios.
No se modificaron datos, modelos, holdout ni archivos reservados.
