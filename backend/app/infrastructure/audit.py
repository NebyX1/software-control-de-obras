"""Auditoría funcional append-only con cadena de hashes.

Cada evento enlaza el hash del anterior. La escritura se serializa con un bloqueo sobre `audit_head` dentro de la misma
transacción de negocio (el último recurso bloqueado, para mantener un orden de bloqueos consistente). Triggers de la base
impiden UPDATE/DELETE sobre `audit_event`. Un administrador de infraestructura con acceso total a la base podría
eludirlo: la verificación de integridad y la exportación permiten detectar alteraciones, no impedirlas absolutamente.
"""
import csv
import io
from flask import request, has_request_context
from sqlalchemy import text
from app.extensions import db
from app.infrastructure.models import AuditEvent, AuditHead
from app.shared.contracts import canonical_json, sha256_hex, iso_utc, utcnow

GENESIS = '0' * 64


def _normalize_details(details):
    import json
    return json.loads(canonical_json(details or {}))


def record(actor, action, resource_type, resource_id=None, case=None, reason=None, reference=None, details=None,
           resource_version=None, role_code=None, assignment_id=None):
    head = db.session.execute(db.select(AuditHead).where(AuditHead.id == 1).with_for_update()).scalar_one()
    details = _normalize_details(details)
    if has_request_context():
        details.setdefault('request_id', getattr(__import__('flask').g, 'request_id', None))
    actor_id = actor.id if actor is not None else None
    actor_name = (actor.full_name if actor is not None else 'Sistema')
    case_id = case.id if case is not None else None
    # Fecha de servidor, fijada antes del INSERT: los triggers impiden cualquier UPDATE posterior.
    event = AuditEvent(case_id=case_id, actor_id=actor_id, actor_name=actor_name, role_code=role_code,
                       assignment_id=assignment_id, action=action, resource_type=resource_type,
                       resource_id=str(resource_id) if resource_id is not None else None, resource_version=resource_version,
                       reason=reason, reference=reference, details=details, prev_hash=head.last_hash,
                       created_at=utcnow(), hash='')
    event.hash = compute_hash(event)
    db.session.add(event)
    db.session.flush()
    head.last_id, head.last_hash = event.id, event.hash
    return event


def event_payload(e):
    return {'case_id': e.case_id, 'actor_id': e.actor_id, 'actor_name': e.actor_name, 'role_code': e.role_code,
            'assignment_id': e.assignment_id, 'action': e.action, 'resource_type': e.resource_type, 'resource_id': e.resource_id,
            'resource_version': e.resource_version, 'reason': e.reason, 'reference': e.reference, 'details': e.details,
            'created_at': e.created_at.isoformat(timespec='microseconds'), 'prev_hash': e.prev_hash}


def compute_hash(e):
    return sha256_hex(canonical_json(event_payload(e)))


def verify_chain(limit=None):
    """Recorre la cadena completa. Devuelve (ok, eventos verificados, primer fallo)."""
    prev, count = GENESIS, 0
    q = db.select(AuditEvent).order_by(AuditEvent.id)
    for e in db.session.scalars(q.execution_options(yield_per=500)):
        if e.prev_hash != prev:
            return False, count, {'id': e.id, 'problem': 'prev_hash no coincide (evento faltante o alterado)'}
        if compute_hash(e) != e.hash:
            return False, count, {'id': e.id, 'problem': 'hash no coincide (contenido alterado)'}
        prev, count = e.hash, count + 1
        if limit and count >= limit:
            break
    head = db.session.get(AuditHead, 1)
    if limit is None and head and head.last_hash != prev:
        return False, count, {'id': None, 'problem': 'la cabecera de auditoría no coincide con el último evento'}
    return True, count, None


def csv_cell(value):
    """Neutraliza inicios de fórmula para hojas de cálculo."""
    s = '' if value is None else str(value)
    if s[:1] in ('=', '+', '-', '@', '\t', '\r') or s.lstrip()[:1] in ('=', '+', '-', '@'):
        s = "'" + s
    return s


def export_csv(events):
    out = io.StringIO()
    out.write('\ufeff')
    w = csv.writer(out, delimiter=';', quoting=csv.QUOTE_ALL, lineterminator='\r\n')
    w.writerow(['Evento', 'Fecha (UTC)', 'Expediente', 'Actor', 'Rol', 'Acción', 'Recurso', 'Versión', 'Motivo', 'Referencia', 'Hash'])
    for e, code in events:
        w.writerow([csv_cell(x) for x in (e.id, iso_utc(e.created_at), code or '', e.actor_name, e.role_code or '', e.action,
                                          f'{e.resource_type}:{e.resource_id or ""}', e.resource_version or '', e.reason or '',
                                          e.reference or '', e.hash)])
    return out.getvalue()
