"""Identidad, roles, competencias, delegaciones, segregación y organización."""
from flask_login import UserMixin
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from app.extensions import db
from .base import ts, ts_null, fk, Money

ph = PasswordHasher()


class Area(db.Model):
    __tablename__ = 'area'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = ts()


class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active_flag = db.Column('is_active', db.Boolean, nullable=False, default=True)
    area_id = fk('area.id', nullable=True)
    failed_logins = db.Column(db.Integer, nullable=False, default=0)
    locked_until = ts_null()
    auth_epoch = db.Column(db.Integer, nullable=False, default=1)  # se incrementa para invalidar sesiones
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    last_login_at = ts_null()
    created_at = ts()
    updated_at = db.Column(db.DateTime, nullable=True)

    area = db.relationship('Area')

    @property
    def is_active(self):  # Flask-Login
        return bool(self.is_active_flag)

    def get_id(self):
        return f'{self.id}:{self.auth_epoch}'

    def set_password(self, password):
        self.password_hash = ph.hash(password)

    def check_password(self, password):
        try:
            return ph.verify(self.password_hash, password)
        except (VerifyMismatchError, InvalidHashError, Exception):
            return False


class UserRole(db.Model):
    """Asignación de un rol con alcance (área), vigencia y competencia. El nombre del perfil no basta."""
    __tablename__ = 'user_role'
    id = db.Column(db.Integer, primary_key=True)
    user_id = fk('user.id')
    role_code = db.Column(db.String(30), nullable=False, index=True)
    area_id = fk('area.id', nullable=True)  # NULL = todas las áreas
    valid_from = db.Column(db.DateTime, nullable=False)
    valid_to = ts_null()
    max_amount = db.Column(Money, nullable=True)  # competencia por monto (ordenador); NULL = sin tope declarado
    procedures = db.Column(db.JSON, nullable=True)  # tipos de procedimiento habilitados; NULL = todos
    delegated_from_id = fk('user.id', nullable=True)
    legal_basis = db.Column(db.String(255), nullable=True)  # resolución / delegación que respalda la competencia
    created_by = fk('user.id', nullable=True)
    created_at = ts()
    revoked_at = ts_null()
    revoked_by = fk('user.id', nullable=True)
    user = db.relationship('User', foreign_keys=[user_id])


class SegregationRule(db.Model):
    __tablename__ = 'segregation_rule'
    id = db.Column(db.Integer, primary_key=True)
    action_a = db.Column(db.String(60), nullable=False)
    action_b = db.Column(db.String(60), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    reason = db.Column(db.String(255), nullable=False)
    __table_args__ = (db.UniqueConstraint('action_a', 'action_b', name='uq_segregation_pair'),)


class TwoFactorCode(db.Model):
    __tablename__ = 'two_factor_code'
    id = db.Column(db.Integer, primary_key=True)
    user_id = fk('user.id', ondelete='CASCADE')
    code_hash = db.Column(db.String(255), nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    expires_at = db.Column(db.DateTime, nullable=False)
    consumed_at = ts_null()
    created_at = ts()

    @staticmethod
    def make(user_id, code, expires_at):
        return TwoFactorCode(user_id=user_id, code_hash=ph.hash(code), expires_at=expires_at)

    def verify(self, code, now):
        if self.consumed_at is not None or now > self.expires_at:
            return False
        try:
            return ph.verify(self.code_hash, code)
        except Exception:
            return False


class RateWindow(db.Model):
    __tablename__ = 'rate_window'
    key = db.Column(db.String(120), primary_key=True)
    count = db.Column(db.Integer, nullable=False, default=0)
