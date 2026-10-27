FROM python:3.13.7-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AERIS_ENV=beta
WORKDIR /app
COPY requirements-web.txt requirements-web-linux.lock ./
RUN pip install --no-cache-dir --only-binary=:all: --require-hashes -r requirements-web-linux.lock && pip check
COPY app.py wsgi.py gunicorn.conf.py ./
COPY railway_start.py ./
COPY railway_acceptance.py ./
COPY aeris_web/ ./aeris_web/
COPY cuentas/ ./cuentas/
COPY data_ingestion/__init__.py data_ingestion/catalog.py data_ingestion/visibility.py ./data_ingestion/
COPY data/openaq_stations.json ./data/openaq_stations.json
COPY templates/ ./templates/
COPY static/v2/ ./static/v2/
COPY static/logo.png ./static/logo.png
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://localhost:'+os.environ.get('PORT','8000')+'/health/ready',timeout=8).read()"]
CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:application"]
