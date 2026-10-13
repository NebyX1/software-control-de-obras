"""Validación de entradas de acciones: mensajes claros y errores por campo."""
from decimal import Decimal
from app.shared.contracts import to_decimal, parse_date, parse_local_datetime
from app.shared.errors import ApiError


def _err(key, label, message):
    raise ApiError('validation', f'{label}: {message}', 422, {key: message})


def text(data, key, label, min_len=1, max_len=500, required=True, default=None):
    value = data.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            _err(key, label, 'es obligatorio.')
        return default
    if not isinstance(value, str):
        _err(key, label, 'debe ser texto.')
    value = value.strip()
    if len(value) < min_len:
        _err(key, label, f'requiere al menos {min_len} caracteres.')
    if len(value) > max_len:
        _err(key, label, f'admite hasta {max_len} caracteres.')
    if any(ord(c) < 32 and c not in '\n\r\t' for c in value):
        _err(key, label, 'contiene caracteres no válidos.')
    return value


def choice(data, key, label, options, required=True, default=None):
    value = data.get(key)
    if value in (None, ''):
        if required:
            _err(key, label, 'es obligatorio.')
        return default
    if value not in options:
        _err(key, label, 'opción no válida.')
    return value


def decimal(data, key, label, required=True, positive=True, places=None, default=None, maximum=None):
    value = data.get(key)
    if value in (None, ''):
        if required:
            _err(key, label, 'es obligatorio.')
        return default
    d = to_decimal(value, key, places=places)
    if positive and d <= 0:
        _err(key, label, 'debe ser mayor que cero.')
    if maximum is not None and d > Decimal(maximum):
        _err(key, label, f'no puede superar {maximum}.')
    return d


def integer(data, key, label, required=True, minimum=0, maximum=10 ** 9, default=None):
    value = data.get(key)
    if value in (None, ''):
        if required:
            _err(key, label, 'es obligatorio.')
        return default
    try:
        if isinstance(value, bool) or (isinstance(value, float) and value != int(value)):
            raise ValueError
        n = int(str(value).strip())
    except ValueError:
        _err(key, label, 'debe ser un número entero.')
    if not minimum <= n <= maximum:
        _err(key, label, f'debe estar entre {minimum} y {maximum}.')
    return n


def day(data, key, label, required=True, default=None):
    value = data.get(key)
    if value in (None, ''):
        if required:
            _err(key, label, 'es obligatorio.')
        return default
    return parse_date(value, label)


def moment(data, key, label, required=True, default=None):
    value = data.get(key)
    if value in (None, ''):
        if required:
            _err(key, label, 'es obligatorio.')
        return default
    return parse_local_datetime(value, label)


def boolean(data, key, default=False):
    value = data.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'on', 'yes')
    return bool(value)


def items(data, key, label, minimum=1, maximum=200):
    value = data.get(key)
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        _err(key, label, f'cargá entre {minimum} y {maximum} elementos.')
    if not all(isinstance(v, dict) for v in value):
        _err(key, label, 'formato inválido.')
    return value
