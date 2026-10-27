import os

port = int(os.environ.get('PORT', '8000'))
if not 1 <= port <= 65535:
    raise ValueError('PORT must be between 1 and 65535')
bind = f'0.0.0.0:{port}'
workers = 1
worker_class = 'gthread'
threads = 2
timeout = 60
graceful_timeout = 30
keepalive = 2
max_requests = 500
max_requests_jitter = 50
limit_request_line = 4094
limit_request_fields = 50
limit_request_field_size = 4094
accesslog = '-'
errorlog = '-'
# Exclude query strings, headers and credentials from access logging.
access_log_format = '%(t)s %(m)s %(U)s %(s)s %(L)s'
capture_output = True
preload_app = False


def post_worker_init(worker):
    # Cada trabajador (también tras max_requests) prepara los resúmenes de la portada sin bloquear.
    from aeris_web import precalentar
    precalentar(worker.wsgi)
