"""Aritmética decimal, serialización sin pérdida de precisión y utilidades de tiempo."""
import hashlib
import json
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation, getcontext
from zoneinfo import ZoneInfo

getcontext().prec = 50
TWO = Decimal('0.01')
FOUR = Decimal('0.0001')
MONTEVIDEO = ZoneInfo('America/Montevideo')
MAX_MONEY = Decimal('9999999999999.99')


def to_decimal(value, field='valor', allow_negative=False, places=None):
    """Convierte texto/entero a Decimal sin pasar por float. Acepta coma decimal; rechaza separadores de miles ambiguos."""
    from app.shared.errors import ApiError
    if isinstance(value, bool) or value is None or isinstance(value, float):
        raise ApiError('invalid_number', f'{field}: ingresá un número válido (sin notación científica).', 422, {field: 'Número inválido'})
    s = str(value).strip().replace(',', '.')
    if s.count('.') > 1 or not s or any(c not in '0123456789.-' for c in s):
        raise ApiError('invalid_number', f'{field}: ingresá un número válido, sin separador de miles.', 422, {field: 'Número inválido'})
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ApiError('invalid_number', f'{field}: número inválido.', 422, {field: 'Número inválido'})
    if not d.is_finite() or (d < 0 and not allow_negative) or abs(d) > MAX_MONEY:
        raise ApiError('invalid_number', f'{field}: fuera del rango admitido.', 422, {field: 'Fuera de rango'})
    if places is not None and -d.as_tuple().exponent > places and d != d.quantize(Decimal(1).scaleb(-places)):
        raise ApiError('invalid_number', f'{field}: admite hasta {places} decimales.', 422, {field: f'Máximo {places} decimales'})
    return d


def money(d):
    """Redondeo monetario oficial del sistema: 2 decimales, mitad hacia arriba."""
    return Decimal(d).quantize(TWO, rounding=ROUND_HALF_UP)


def qty(d):
    return Decimal(d).quantize(FOUR, rounding=ROUND_HALF_UP)


def dstr(d):
    """Serializa Decimal sin notación científica y sin perder precisión."""
    if d is None:
        return None
    return format(Decimal(d), 'f')


def display2(d):
    return dstr(Decimal(d).quantize(TWO, rounding=ROUND_HALF_UP))


def canonical_json(value):
    def default(o):
        if isinstance(o, Decimal):
            return dstr(o)
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        raise TypeError(type(o))
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=default)


def sha256_hex(value):
    data = value if isinstance(value, bytes) else str(value).encode()
    return hashlib.sha256(data).hexdigest()


def canonical_hash(value):
    return sha256_hex(canonical_json(value))


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso_utc(dt):
    return None if dt is None else dt.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')


def to_local(dt):
    return dt.replace(tzinfo=timezone.utc).astimezone(MONTEVIDEO)


def parse_local_datetime(text, field='fecha'):
    """Interpreta un instante recibido del cliente. Sin zona explícita se toma America/Montevideo. Devuelve UTC naive."""
    from app.shared.errors import ApiError
    try:
        dt = datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except ValueError:
        raise ApiError('invalid_datetime', f'{field}: fecha y hora inválidas.', 422, {field: 'Fecha inválida'})
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MONTEVIDEO)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def parse_date(text, field='fecha'):
    from app.shared.errors import ApiError
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        raise ApiError('invalid_date', f'{field}: fecha inválida.', 422, {field: 'Fecha inválida'})
