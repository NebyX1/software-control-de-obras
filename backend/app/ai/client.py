"""Cliente Ollama (API nativa), con la forma de conexión de `sample/rag-chat` (Bearer + modelo sin sufijo `:cloud` en conexión directa).

No se asume compatibilidad cloud con `format`, JSON Schema ni tool calling: la validación estricta de las respuestas se hace en nuestra
aplicación. Límites de concurrencia, tiempo de espera y reintentos acotados; 401/403 no se reintentan.
"""
import json
import threading
import time
from urllib.parse import urlparse
import httpx
from flask import current_app

_sem = {}
_sem_lock = threading.Lock()


class ProviderError(Exception):
    def __init__(self, code, message, status=None, retry_after=None):
        super().__init__(message)
        self.code, self.status, self.retry_after = code, status, retry_after


MESSAGES = {
    'auth': 'El proveedor de IA rechazó las credenciales (401/403). Verificá OLLAMA_API_KEY o la sesión del daemon Ollama.',
    'model_unavailable': 'El modelo configurado no está disponible en el endpoint.',
    'model_retired': 'El modelo configurado fue retirado por el proveedor. Configurá un modelo disponible en OLLAMA_MODEL.',
    'rate_limited': 'El proveedor de IA limitó las solicitudes (429). Reintentá en unos minutos.',
    'provider_error': 'El proveedor de IA respondió con un error.',
    'timeout': 'El proveedor de IA no respondió a tiempo.',
    'unreachable': 'No se pudo conectar con el proveedor de IA.',
    'empty': 'El proveedor devolvió una respuesta vacía.',
    'busy': 'La asistencia está ocupada; reintentá en unos segundos.',
    'disabled': 'La asistencia automática no está habilitada.',
    'unconfigured': 'Falta configurar el modelo de IA (OLLAMA_MODEL / OLLAMA_HOST).',
    'interrupted': 'La respuesta se interrumpió antes de terminar.',
}


def config():
    c = current_app.config
    return {'host': c['OLLAMA_HOST'], 'key': c['OLLAMA_API_KEY'], 'model': c['OLLAMA_MODEL'], 'enabled': c['AI_ENABLED'], 'timeout': c['AI_TIMEOUT_SECONDS'],
            'retries': c['AI_MAX_RETRIES'], 'concurrency': c['AI_MAX_CONCURRENCY']}


def is_direct_cloud(host):
    return (urlparse(host).hostname or '').endswith('ollama.com')


def effective_model(cfg):
    m = cfg['model']
    return m.removesuffix(':cloud') if is_direct_cloud(cfg['host']) else m


def check_ready():
    cfg = config()
    if not cfg['enabled']:
        raise ProviderError('disabled', MESSAGES['disabled'])
    if not cfg['model'] or not cfg['host']:
        raise ProviderError('unconfigured', MESSAGES['unconfigured'])
    return cfg


def _semaphore(n):
    with _sem_lock:
        if n not in _sem:
            _sem[n] = threading.BoundedSemaphore(n)
        return _sem[n]


def _map_status(resp):
    code = resp.status_code
    detail = ''
    try:
        detail = str(resp.json().get('error', ''))[:160]
    except Exception:
        pass
    if code in (401, 403):
        return ProviderError('auth', MESSAGES['auth'], code)
    if code == 410:
        return ProviderError('model_retired', MESSAGES['model_retired'] + (f' ({detail})' if detail else ''), code)
    if code == 404:
        return ProviderError('model_unavailable', MESSAGES['model_unavailable'], code)
    if code == 429:
        ra = resp.headers.get('Retry-After')
        return ProviderError('rate_limited', MESSAGES['rate_limited'], code, int(ra) if ra and ra.isdigit() else None)
    return ProviderError('provider_error', MESSAGES['provider_error'] + f' (HTTP {code})', code)


def _headers(cfg):
    h = {'Content-Type': 'application/json'}
    if cfg['key']:
        h['Authorization'] = f'Bearer {cfg["key"]}'
    return h


def _payload(cfg, messages, stream, options):
    return {'model': effective_model(cfg), 'messages': messages, 'stream': stream, 'think': False,
            'options': {'temperature': 0.1, 'num_predict': 1400, **(options or {})}}


def chat(messages, options=None):
    """Una respuesta completa. Devuelve (texto, metadatos)."""
    cfg = check_ready()
    sem = _semaphore(cfg['concurrency'])
    if not sem.acquire(timeout=5):
        raise ProviderError('busy', MESSAGES['busy'])
    started = time.monotonic()
    try:
        attempts = cfg['retries'] + 1
        last = None
        for attempt in range(attempts):
            try:
                with httpx.Client(timeout=httpx.Timeout(cfg['timeout'], connect=10)) as client:
                    payload = _payload(cfg, messages, False, options)
                    r = client.post(f'{cfg["host"]}/api/chat', json=payload, headers=_headers(cfg))
                    if r.status_code == 400 and 'think' in r.text.lower():
                        payload.pop('think')
                        r = client.post(f'{cfg["host"]}/api/chat', json=payload, headers=_headers(cfg))
                if r.status_code != 200:
                    last = _map_status(r)
                    if r.status_code in (429, 502, 503, 504) and attempt + 1 < attempts:
                        time.sleep(min(last.retry_after or 2, 5))
                        continue
                    raise last
                text = ((r.json().get('message') or {}).get('content') or '').strip()
                if not text:
                    raise ProviderError('empty', MESSAGES['empty'])
                return text, {'model': cfg['model'], 'latency_ms': int((time.monotonic() - started) * 1000), 'attempts': attempt + 1}
            except httpx.TimeoutException:
                last = ProviderError('timeout', MESSAGES['timeout'])
            except httpx.TransportError:
                last = ProviderError('unreachable', MESSAGES['unreachable'])
            if attempt + 1 < attempts:
                time.sleep(1)
        raise last or ProviderError('provider_error', MESSAGES['provider_error'])
    finally:
        sem.release()


def stream(messages, options=None):
    """Generador de fragmentos de texto. Una interrupción levanta ProviderError('interrupted')."""
    cfg = check_ready()
    sem = _semaphore(cfg['concurrency'])
    if not sem.acquire(timeout=5):
        raise ProviderError('busy', MESSAGES['busy'])
    got_any = False
    try:
        with httpx.Client(timeout=httpx.Timeout(cfg['timeout'], connect=10, read=cfg['timeout'])) as client:
            try:
                with client.stream('POST', f'{cfg["host"]}/api/chat', json=_payload(cfg, messages, True, options), headers=_headers(cfg)) as r:
                    if r.status_code != 200:
                        r.read()
                        raise _map_status(r)
                    done = False
                    for line in r.iter_lines():
                        if not line:
                            continue
                        obj = json.loads(line)
                        piece = (obj.get('message') or {}).get('content') or ''
                        if piece:
                            got_any = True
                            yield piece
                        if obj.get('done'):
                            done = True
                    if not got_any:
                        raise ProviderError('empty', MESSAGES['empty'])
                    if not done:
                        raise ProviderError('interrupted', MESSAGES['interrupted'])
            except httpx.TimeoutException:
                raise ProviderError('interrupted' if got_any else 'timeout', MESSAGES['interrupted' if got_any else 'timeout'])
            except httpx.TransportError:
                raise ProviderError('interrupted' if got_any else 'unreachable', MESSAGES['interrupted' if got_any else 'unreachable'])
    finally:
        sem.release()
