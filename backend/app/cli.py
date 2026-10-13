"""Comandos de operación: alta segura del primer administrador, configuración base, semillas opcionales, verificación."""
import os
import click
from sqlalchemy.exc import IntegrityError
from app.extensions import db


def register_cli(app):
    @app.cli.command('seed-base')
    def seed_base():
        """Configuración base idempotente: reglas vigentes, normativa catalogada y segregación. No crea usuarios ni expedientes."""
        from app.bootstrap import ensure_base_config
        ensure_base_config()
        click.echo('Configuración base lista.')

    @app.cli.command('create-admin')
    @click.option('--username', required=True)
    @click.option('--email', required=True)
    @click.option('--full-name', required=True)
    def create_admin(username, email, full_name):
        """Crea un administrador. La contraseña se toma de CC_ADMIN_PASSWORD o se solicita sin eco: nunca como argumento."""
        from app.infrastructure.models import User, UserRole
        from app.modules.identity.service import validate_password
        from app.shared.contracts import utcnow
        from app.shared.errors import ApiError
        password = os.environ.get('CC_ADMIN_PASSWORD') or click.prompt('Contraseña', hide_input=True, confirmation_prompt=True)
        try:
            validate_password(password, username)
        except ApiError as exc:
            raise click.ClickException(exc.message)
        email = email.strip().lower()
        if '@' not in email:
            raise click.ClickException('Correo inválido.')
        user = User(username=username.strip(), email=email, full_name=full_name.strip())
        user.set_password(password)
        db.session.add(user)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            raise click.ClickException('Ya existe un usuario con ese nombre o correo.')
        db.session.add(UserRole(user_id=user.id, role_code='administrador', valid_from=utcnow(), legal_basis='Alta inicial por línea de comandos'))
        from app.infrastructure import audit
        audit.record(None, 'admin.first_admin_created', 'user', user.id, reason=username)
        db.session.commit()
        click.echo(f'Administrador creado (id={user.id}).')

    @app.cli.command('seed-demo')
    @click.option('--confirm', is_flag=True, help='Confirma que se cargan datos ficticios.')
    def seed_demo(confirm):
        """Carga los cinco expedientes de ejemplo y usuarios de prueba. Solo con ALLOW_DEMO_SEED=true."""
        if not app.config.get('ALLOW_DEMO_SEED'):
            raise click.ClickException('ALLOW_DEMO_SEED no está habilitado: las semillas demo nunca se cargan en producción.')
        if not confirm:
            raise click.ClickException('Agregá --confirm para cargar datos ficticios.')
        from app.demo_seed import seed
        result = seed()
        if result['credentials']:
            click.echo('Credenciales demo: se muestran una sola vez y no se guardan en el repositorio.')
            for username, password in result['credentials']:
                click.echo(f'  {username}: {password}')
        else:
            click.echo('Usuarios demo ya existentes: no se generaron contraseñas nuevas.')
        click.echo(f"Proveedores demo creados: {result['suppliers_created']}.")
        for case in result['cases']:
            failure = f" (detenido en {case['failure']})" if case.get('failure') else ''
            click.echo(f"{case['html_id']} -> {case['code'] or '-'}: {case['status']}{failure}")
            click.echo(f"    no cargado: {case['omitted']}")
        for note in result['general_omissions']:
            click.echo(f'Nota: {note}')

    @app.cli.command('audit-verify')
    def audit_verify():
        from app.infrastructure.audit import verify_chain
        ok, count, failure = verify_chain()
        click.echo(f'ok={ok} verificados={count} fallo={failure}')
        raise SystemExit(0 if ok else 2)

    @app.cli.command('reconcile-storage')
    @click.option('--delete-orphans', is_flag=True)
    def reconcile_storage(delete_orphans):
        import time
        from app.infrastructure.models import DocumentVersion
        from app.infrastructure.storage import get_document_storage
        storage = get_document_storage()
        referenced = {v.storage_key for v in db.session.scalars(db.select(DocumentVersion))}
        missing = [k for k in referenced if not storage.exists(k)]
        orphans = [o.key for o in storage.list_objects() if o.key not in referenced and time.time() - o.modified_at > 3600]
        if delete_orphans:
            for k in orphans:
                storage.delete(k)
        click.echo(f'faltantes={len(missing)} huerfanos={len(orphans)} eliminados={delete_orphans}')

    @app.cli.command('ai-index-normative')
    def ai_index_normative():
        """Indexa el catálogo normativo y el informe de diseño (con ámbito, vigencia y estado de validación)."""
        from app.ai.rag.normative_index import index_normative
        click.echo(index_normative())
