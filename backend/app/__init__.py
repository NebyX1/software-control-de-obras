import time
from uuid import uuid4
from flask import Flask, jsonify, g, request
from sqlalchemy import text
from werkzeug.exceptions import HTTPException
from app.extensions import db, migrate, login_manager, mail
from app.shared.errors import ApiError


def create_app(test_config=None):
    from pathlib import Path
    from app.config import settings
    root = Path(__file__).resolve().parents[2]
    app = Flask(__name__)
    app.config.update(settings())
    if test_config:
        app.config.update(test_config)
    if not app.config.get('SECRET_KEY'):
        raise RuntimeError('Configure SECRET_KEY en el entorno de despliegue (no en el código).')
    if not app.config.get('SQLALCHEMY_DATABASE_URI'):
        raise RuntimeError('Configure DATABASE_URI.')
    if app.config['TRUST_PROXY']:
        # Solo si la API es inalcanzable fuera del proxy (ver docs/DESPLIEGUE_COOLIFY.md).
        from werkzeug.middleware.proxy_fix import ProxyFix
        hops = app.config['TRUSTED_PROXY_HOPS']
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=1, x_host=1)
    db.init_app(app)
    migrate.init_app(app, db, directory=str(root / 'backend' / 'migrations'))
    mail.init_app(app)
    login_manager.init_app(app)

    from app.infrastructure import models
    from app.modules.identity import service as _identity_service  # noqa: F401  registra user_loader
    from app.modules.identity.routes import bp as auth_bp
    from app.modules.procurement.routes import bp as procurement_bp
    from app.modules.documents.routes import bp as documents_bp
    from app.modules.organization.routes import bp as organization_bp
    from app.modules.rules.routes import bp as rules_bp
    from app.modules.audit.routes import bp as audit_bp
    from app.modules.admin.routes import bp as admin_bp
    from app.modules.integrations.routes import bp as integrations_bp
    from app.ai.routes import bp as ai_bp
    for bp in (auth_bp, procurement_bp, documents_bp, organization_bp, rules_bp, audit_bp, admin_bp, integrations_bp, ai_bp):
        app.register_blueprint(bp)

    from app.modules.identity.service import protect_csrf, auth_required

    @app.before_request
    def request_context():
        g.request_id, g.started = str(uuid4()), time.monotonic()
        if request.path.startswith('/api/'):
            protect_csrf()

    @app.after_request
    def headers(response):
        response.headers['X-Request-ID'] = getattr(g, 'request_id', '-')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        if request.path.startswith('/api/') and 'Cache-Control' not in response.headers:
            response.headers['Cache-Control'] = 'no-store'
        response.headers.setdefault('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")
        return response

    def error_body(exc):
        body = {'code': exc.code, 'message': exc.message, 'fields': exc.fields, 'request_id': getattr(g, 'request_id', None)}
        body.update(exc.extra)
        return body

    @app.errorhandler(ApiError)
    def api_error(exc):
        db.session.rollback()
        response = jsonify(error_body(exc))
        if exc.status == 429:
            response.headers['Retry-After'] = '60'
        return response, exc.status

    @app.errorhandler(HTTPException)
    def http_error(exc):
        db.session.rollback()
        messages = {404: 'No encontrado.', 405: 'Método no permitido.', 413: 'El archivo supera el límite admitido.', 401: 'Iniciá sesión para continuar.'}
        return jsonify(code='http_error', message=messages.get(exc.code, 'No se pudo completar esta petición.'), fields={}, request_id=getattr(g, 'request_id', None)), exc.code

    @app.errorhandler(Exception)
    def unexpected(exc):
        db.session.rollback()
        app.logger.error('request_failed request_id=%s type=%s path=%s', getattr(g, 'request_id', '-'), type(exc).__name__, request.path)
        return jsonify(code='server_error', message='No se pudo completar la operación. Los cambios confirmados se conservan; podés reintentar.', fields={},
                       request_id=getattr(g, 'request_id', None)), 500

    @app.get('/api/v1/health/live')
    def live():
        return jsonify(status='alive')

    @app.get('/api/v1/health/ready')
    def ready():
        from app.infrastructure.storage import get_document_storage
        from app.modules.rules.service import active_rule_set
        db.session.execute(text('SELECT 1'))
        storage = get_document_storage()
        if not storage.healthy():
            raise ApiError('storage_unavailable', 'Almacenamiento no disponible.', 503)
        if db.session.get(models.AuditHead, 1) is None:
            raise ApiError('not_initialized', 'Base sin configuración inicial (ejecutar seed-base).', 503)
        return jsonify(status='ready', database='MariaDB', storage=storage.kind, rules=bool(active_rule_set()))

    @app.get('/api/v1/health/ai')
    @auth_required
    def ai_health():
        from app.ai.health import ai_status
        return jsonify(ai_status())

    from app.cli import register_cli
    register_cli(app)
    return app
