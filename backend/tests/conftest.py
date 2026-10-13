"""Fixtures de pruebas con MariaDB real: base aislada por sesión, migraciones reales y usuarios por rol."""
import os
import secrets
import shutil
import tempfile
import pytest
from sqlalchemy import create_engine, text

ROOT_URI = os.environ.get('TEST_DB_ADMIN_URI', 'mysql+pymysql://root:devroot-only-local@127.0.0.1:33306/?charset=utf8mb4')
APP_USER = os.environ.get('TEST_DB_APP_USER', 'cc:ccdev-only-local')
DB_HOST = os.environ.get('TEST_DB_HOST', '127.0.0.1:33306')

ROLES = ['solicitante', 'solicitante2', 'compras', 'contaduria', 'tecnica', 'comision', 'control', 'ordenador', 'ordenador2', 'recepcion', 'tesoreria',
         'auditor', 'administrador']
PASSWORD = 'Test-Only-Passw0rd!x'


@pytest.fixture(scope='session')
def db_name():
    name = f'cc_test_{secrets.token_hex(4)}'
    admin = create_engine(ROOT_URI, isolation_level='AUTOCOMMIT')
    user = APP_USER.split(':')[0]
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'))
        c.execute(text(f"GRANT ALL ON `{name}`.* TO '{user}'@'%'"))
    yield name
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS `{name}`'))
    admin.dispose()


@pytest.fixture(scope='session')
def app(db_name):
    docs = tempfile.mkdtemp(prefix='cc-docs-')
    cfg = {'TESTING': True, 'SQLALCHEMY_DATABASE_URI': f'mysql+pymysql://{APP_USER}@{DB_HOST}/{db_name}?charset=utf8mb4', 'SECRET_KEY': 'tests-only-secret-key-0123456789',
           'LOGIN_CAPTCHA': False, 'AUTH_2FA_REQUIRED': False, 'DOCUMENT_STORAGE': 'local', 'DOCUMENT_ROOT': docs, 'EMBEDDER': 'hash', 'AI_ENABLED': False,
           'MAIL_CAPTURE': [], 'ALLOW_DEMO_SEED': True, 'SESSION_COOKIE_SECURE': False, 'RATE_LIMIT_DISABLED': True}
    os.environ['TZ'] = 'UTC'
    from app import create_app
    app = create_app(cfg)
    from flask_migrate import upgrade
    with app.app_context():
        upgrade()
        from app.bootstrap import ensure_base_config
        ensure_base_config()
    yield app
    shutil.rmtree(docs, ignore_errors=True)


class Api:
    def __init__(self, app, name=None):
        self.client = app.test_client()
        self.csrf = None
        self.name = name

    def _refresh(self):
        r = self.client.get('/api/v1/auth/challenge')
        self.csrf = r.get_json()['csrf_token']

    def login(self, email, password=PASSWORD):
        self._refresh()
        r = self.client.post('/api/v1/auth/login', json={'email': email, 'password': password}, headers={'X-CSRF-Token': self.csrf})
        assert r.status_code == 200, r.get_json()
        self.csrf = r.get_json()['csrf_token']
        return r.get_json()['user']

    def get(self, url, **kw):
        return self.client.get(url, **kw)

    def post(self, url, json=None, **kw):
        headers = {'X-CSRF-Token': self.csrf or '', **kw.pop('headers', {})}
        return self.client.post(url, json=json, headers=headers, **kw)

    def patch(self, url, json=None, **kw):
        return self.client.patch(url, json=json, headers={'X-CSRF-Token': self.csrf or ''}, **kw)

    def upload(self, url, data, filename, content, mimetype='text/plain'):
        import io
        data = {**data, 'file': (io.BytesIO(content), filename, mimetype)}
        return self.client.post(url, data=data, headers={'X-CSRF-Token': self.csrf or ''}, content_type='multipart/form-data')


@pytest.fixture(scope='session')
def world(app):
    """Áreas, usuarios y asignaciones vigentes por rol. Las contraseñas son solo de prueba."""
    from app.extensions import db
    from app.infrastructure.models import Area, User, UserRole
    from app.shared.contracts import utcnow
    from datetime import timedelta
    with app.app_context():
        a1 = Area(code='ALUM', name='Alumbrado público')
        a2 = Area(code='VIAL', name='Vialidad')
        db.session.add_all([a1, a2])
        db.session.flush()
        users = {}
        start = utcnow() - timedelta(days=1)
        for role in ROLES:
            code = role.rstrip('2')
            u = User(username=role, email=f'{role}@tests.invalid', full_name=f'Persona {role}', area_id=a1.id if code == 'solicitante' and role == 'solicitante' else (a2.id if role == 'solicitante2' else None))
            u.set_password(PASSWORD)
            db.session.add(u)
            db.session.flush()
            kwargs = {}
            if code == 'ordenador':
                kwargs['legal_basis'] = 'Resolución de delegación de pruebas 1/2026'
            area = a1.id if role == 'solicitante' else (a2.id if role == 'solicitante2' else None)
            db.session.add(UserRole(user_id=u.id, role_code=code, area_id=area, valid_from=start, **kwargs))
            users[role] = u.id
        db.session.commit()
        return {'users': users, 'area1': a1.id, 'area2': a2.id}


@pytest.fixture(scope='session')
def api(app, world):
    """Clientes con sesión iniciada por rol."""
    cache = {}

    class Pool:
        def __getitem__(self, role):
            if role not in cache:
                a = Api(app, role)
                a.login(f'{role}@tests.invalid')
                cache[role] = a
            return cache[role]
    return Pool()
