"""Servicios de identidad: sesión, CSRF, límites de intento y decoradores de acceso."""
import hashlib
import hmac
import secrets
from functools import wraps
from flask import current_app, request, session
from flask_login import current_user
from sqlalchemy.dialects.mysql import insert
from app.extensions import db, login_manager
from app.infrastructure.models import RateWindow, User
from app.modules.identity.permissions import has_perm
from app.shared.contracts import utcnow
from app.shared.errors import ApiError, require


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@login_manager.user_loader
def load_user(session_id):
    try:
        uid, epoch = str(session_id).split(':')
        user = db.session.get(User, int(uid))
    except (ValueError, TypeError):
        return None
    if not user or not user.is_active or user.auth_epoch != int(epoch):
        return None
    if user.locked_until and user.locked_until > utcnow():
        return None
    return user


@login_manager.unauthorized_handler
def unauthorized():
    raise ApiError('auth_required', 'Iniciá sesión para continuar.', 401)


def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return session['csrf']


def check_origin():
    origin = request.headers.get('Origin')
    if not origin:
        return
    allowed = {request.host_url.rstrip('/')}
    if current_app.config.get('PUBLIC_ORIGIN'):
        allowed.add(current_app.config['PUBLIC_ORIGIN'])
    require(origin in allowed, 'origin', 'Origen no permitido.', 403)


def protect_csrf():
    """CSRF por cabecera para toda escritura de la API (el token vive en la sesión firmada, no en JS storage)."""
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return
    check_origin()
    sent = request.headers.get('X-CSRF-Token', '')
    expected = session.get('csrf', '')
    require(expected and hmac.compare_digest(sent, expected), 'csrf', 'La sesión de seguridad cambió. Recargá la página e intentá de nuevo.', 403)


def auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            raise ApiError('auth_required', 'Iniciá sesión para continuar.', 401)
        return fn(*args, **kwargs)
    return wrapper


def perm_required(perm):
    def deco(fn):
        @wraps(fn)
        @auth_required
        def wrapper(*args, **kwargs):
            if not has_perm(current_user, perm):
                raise ApiError('forbidden', 'Tu perfil no tiene permiso para esta operación.', 403)
            return fn(*args, **kwargs)
        return wrapper
    return deco


def client_ip():
    return request.remote_addr or 'local'


def rate_limit(bucket, maximum=15, ip=None):
    """Contador persistente compartido entre workers (ventana de un minuto)."""
    if current_app.config.get('RATE_LIMIT_DISABLED') and bucket not in current_app.config.get('RATE_LIMIT_ALWAYS', ()):
        return
    minute = utcnow().strftime('%Y%m%d%H%M')
    key = digest(ip or client_ip())[:32] + ':' + bucket + ':' + minute
    db.session.execute(insert(RateWindow).values(key=key, count=1).on_duplicate_key_update(count=RateWindow.count + 1))
    count = db.session.get(RateWindow, key, populate_existing=True).count
    db.session.commit()
    require(count <= maximum, 'rate_limit', 'Se alcanzó el límite de intentos. Esperá un minuto y volvé a intentar.', 429)


def validate_password(password, username=''):
    require(isinstance(password, str) and 12 <= len(password) <= 256, 'weak_password', 'La contraseña debe tener entre 12 y 256 caracteres.', 422)
    require(not username or username.lower() not in password.lower(), 'weak_password', 'La contraseña no puede contener el nombre de usuario.', 422)
    classes = sum(any(f(c) for c in password) for f in (str.islower, str.isupper, str.isdigit, lambda c: not c.isalnum()))
    require(classes >= 3, 'weak_password', 'Usá al menos tres tipos de caracteres (minúsculas, mayúsculas, números, símbolos).', 422)
