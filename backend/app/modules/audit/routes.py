"""Auditoría funcional: consulta, exportación CSV y verificación de la cadena de integridad."""
from flask import Blueprint, jsonify, request, Response
from sqlalchemy import or_
from app.extensions import db
from app.infrastructure import audit
from app.infrastructure.models import AuditEvent, ProcurementCase
from app.modules.identity.service import perm_required
from app.modules.procurement.serializers import event_json

bp = Blueprint('audit', __name__, url_prefix='/api/v1/audit')


def _query():
    q = db.select(AuditEvent, ProcurementCase.code).outerjoin(ProcurementCase, ProcurementCase.id == AuditEvent.case_id)
    text = (request.args.get('q') or '').strip()
    if text:
        like = f'%{text[:80]}%'
        q = q.where(or_(ProcurementCase.code.like(like), AuditEvent.actor_name.like(like), AuditEvent.action.like(like), AuditEvent.reason.like(like), AuditEvent.reference.like(like)))
    case = request.args.get('case')
    if case:
        q = q.where(ProcurementCase.code == case)
    return q.order_by(AuditEvent.id.desc())


@bp.get('')
@perm_required('audit.read')
def list_events():
    page, per = max(1, request.args.get('page', 1, type=int)), min(100, request.args.get('per_page', 30, type=int))
    q = _query()
    total = db.session.scalar(db.select(db.func.count()).select_from(q.order_by(None).subquery()))
    rows = db.session.execute(q.limit(per).offset((page - 1) * per)).all()
    return jsonify(items=[{**event_json(e), 'case': code} for e, code in rows], total=total, page=page, per_page=per)


@bp.get('/export')
@perm_required('audit.read')
def export():
    rows = db.session.execute(_query().limit(20000)).all()
    resp = Response(audit.export_csv(rows), mimetype='text/csv; charset=utf-8')
    resp.headers['Content-Disposition'] = 'attachment; filename="auditoria.csv"'
    resp.headers['Cache-Control'] = 'private, no-store'
    return resp


@bp.get('/verify')
@perm_required('audit.verify')
def verify():
    ok, count, failure = audit.verify_chain()
    return jsonify(ok=ok, verified=count, failure=failure,
                   notice='Detecta alteraciones o faltantes en la cadena de hashes. No es una garantía frente a un administrador con acceso total a la infraestructura.')
