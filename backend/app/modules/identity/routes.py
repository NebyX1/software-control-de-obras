"""Autenticación: contraseña (argon2) + captcha firmado + segundo factor por correo + CSRF + bloqueo por intentos."""
import hashlib
import hmac
import secrets
from datetime import timedelta
from flask import Blueprint, current_app, jsonify, request, session
from flask_login import current_user, login_user, logout_user
from app.extensions import db
from app.infrastructure import audit
from app.infrastructure.models import User, TwoFactorCode
from app.modules.identity import mailer
from app.modules.identity.permissions import user_permissions
from app.modules.identity.service import (auth_required, csrf_token, rate_limit, validate_password)
from app.shared.contracts import utcnow
from app.shared.errors import ApiError, require

bp = Blueprint('auth', __name__, url_prefix='/api/v1/auth')
MAX_FAILED = 5
LOCK_MINUTES = 15


def captcha_digest(answer, nonce):
    return hmac.new(current_app.secret_key.encode(), f'{nonce}:{answer}'.encode(), hashlib.sha256).hexdigest()


def user_json(user):
    perms, roles = user_permissions(user)
    return {'id': user.id, 'username': user.username, 'email': user.email, 'full_name': user.full_name,
            'area_id': user.area_id, 'area': user.area.name if user.area else None, 'permissions': perms, 'roles': roles,
            'must_change_password': user.must_change_password}


@bp.get('/challenge')
def challenge():
    data = {'csrf_token': csrf_token(), 'captcha': None, 'two_factor': bool(current_app.config['AUTH_2FA_REQUIRED'])}
    if current_app.config['LOGIN_CAPTCHA']:
        a, b = secrets.randbelow(11) + 2, secrets.randbelow(11) + 2
        nonce = secrets.token_hex(16)
        session['captcha'] = [nonce, captcha_digest(str(a + b), nonce)]
        data['captcha'] = {'question': f'¿Cuánto es {a} + {b}?'}
    return jsonify(data)


def _fail_login(user, email):
    if user:
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED:
            user.locked_until = utcnow() + timedelta(minutes=LOCK_MINUTES)
            user.failed_logins = 0
    audit.record(user, 'auth.login_failed', 'user', user.id if user else None, details={'email_hash': hashlib.sha256(email.encode()).hexdigest()[:16]})
    db.session.commit()
    raise ApiError('invalid_credentials', 'Credenciales inválidas o cuenta bloqueada temporalmente.', 401)


@bp.post('/login')
def login():
    rate_limit('login', 10)
    data = request.get_json(silent=True)
    require(isinstance(data, dict), 'invalid_json', 'Datos inválidos.', 422)
    if current_app.config['LOGIN_CAPTCHA']:
        challenge_ = session.pop('captcha', None)
        answer = str(data.get('captcha', '')).strip()
        require(challenge_ and hmac.compare_digest(challenge_[1], captcha_digest(answer, challenge_[0])),
                'captcha_invalid', 'Verificación de seguridad inválida.', 400)
    email, password = data.get('email'), data.get('password')
    require(isinstance(email, str) and isinstance(password, str) and len(password) <= 1024, 'invalid_credentials', 'Ingresá correo y contraseña.', 422)
    email = email.strip().lower()
    user = db.session.scalar(db.select(User).where(User.email == email).with_for_update())
    if not user or not user.is_active or (user.locked_until and user.locked_until > utcnow()) or not user.check_password(password):
        _fail_login(user, email)
    user.failed_logins = 0
    if not current_app.config['AUTH_2FA_REQUIRED']:
        return _finish_login(user)
    for old in db.session.scalars(db.select(TwoFactorCode).where(TwoFactorCode.user_id == user.id, TwoFactorCode.consumed_at.is_(None))):
        old.consumed_at = utcnow()
    code = ''.join(secrets.choice('0123456789') for _ in range(6))
    row = TwoFactorCode.make(user.id, code, utcnow() + timedelta(minutes=10))
    db.session.add(row)
    db.session.commit()
    row_id, recipient = row.id, user.email
    db.session.remove()
    try:
        mailer.send_2fa_email(recipient, code)  # sin transacción abierta durante SMTP; el código nunca se registra
    except Exception as exc:
        db.session.get(TwoFactorCode, row_id).consumed_at = utcnow()
        db.session.commit()
        current_app.logger.warning('2fa_mail_failed type=%s', type(exc).__name__)
        raise ApiError('mail_unavailable', 'No se pudo enviar el código de verificación. Reintentá en unos minutos.', 503)
    session['2fa_id'] = row_id
    local, _, domain = recipient.partition('@')
    return jsonify(requires_2fa=True, preview=local[:2] + '***@' + domain)


def _finish_login(user):
    user.last_login_at = utcnow()
    audit.record(user, 'auth.login', 'user', user.id)
    db.session.commit()
    csrf = session.get('csrf')
    session.clear()
    login_user(user)
    session.permanent = True
    session['csrf'] = csrf or csrf_token()
    return jsonify(user=user_json(user), csrf_token=session['csrf'])


@bp.post('/verify-2fa')
def verify_2fa():
    rate_limit('verify2fa', 10)
    data = request.get_json(silent=True) or {}
    code = data.get('code', '') if isinstance(data, dict) else ''
    row_id = session.get('2fa_id')
    require(row_id, 'session_expired', 'La verificación expiró. Volvé a iniciar sesión.', 401)
    row = db.session.scalar(db.select(TwoFactorCode).where(TwoFactorCode.id == row_id).with_for_update())
    user = db.session.get(User, row.user_id) if row else None
    ok = bool(row and user and user.is_active and row.attempts < 5 and isinstance(code, str) and row.verify(code.strip(), utcnow()))
    if not ok:
        if row:
            row.attempts += 1
        audit.record(user, 'auth.2fa_failed', 'user', user.id if user else None)
        db.session.commit()
        raise ApiError('invalid_code', 'Código inválido o vencido.', 400)
    row.consumed_at = utcnow()
    session.pop('2fa_id', None)
    return _finish_login(user)


@bp.post('/logout')
@auth_required
def logout():
    audit.record(current_user, 'auth.logout', 'user', current_user.id)
    db.session.commit()
    logout_user()
    session.clear()
    return jsonify(ok=True, csrf_token=csrf_token())


@bp.get('/me')
@auth_required
def me():
    return jsonify(user=user_json(current_user), csrf_token=csrf_token())


@bp.post('/change-password')
@auth_required
def change_password():
    rate_limit('chpass', 10)
    data = request.get_json(silent=True) or {}
    require(current_user.check_password(str(data.get('current', ''))), 'invalid_credentials', 'La contraseña actual no es correcta.', 400)
    validate_password(data.get('new'), current_user.username)
    current_user.set_password(data['new'])
    current_user.must_change_password = False
    current_user.auth_epoch += 1
    audit.record(current_user, 'auth.password_changed', 'user', current_user.id)
    db.session.commit()
    logout_user()
    session.clear()
    return jsonify(ok=True)
