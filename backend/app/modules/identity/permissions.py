"""Roles, permisos por acción y alcance por recurso.

El nombre de un perfil no concede competencia administrativa: los permisos salen de asignaciones vigentes
(`user_role`) con alcance de área, vigencia y, para el ordenador, tope/procedimientos habilitados.
"""
from sqlalchemy import or_
from app.extensions import db
from app.infrastructure.models import UserRole
from app.shared.contracts import utcnow

ROLE_NAMES = {
    'solicitante': 'Solicitante', 'compras': 'Compras', 'contaduria': 'Contaduría', 'tecnica': 'Técnica',
    'comision': 'Comisión', 'control': 'Control', 'ordenador': 'Ordenador', 'recepcion': 'Recepción',
    'tesoreria': 'Tesorería', 'auditor': 'Auditor', 'administrador': 'Administrador',
}

COMMON = {'case.read', 'document.read', 'normative.read', 'rules.read', 'supplier.read', 'ai.use', 'dashboard.read', 'evaluation.read'}

ROLE_PERMS = {
    'solicitante': COMMON | {'case.create', 'case.edit_draft', 'case.submit', 'document.upload'},
    'compras': COMMON | {'case.create', 'case.edit_draft', 'case.submit', 'case.receive', 'case.classify', 'spec.manage', 'publicity.register',
                         'envelope.register', 'deadline.extend', 'opening.perform', 'offer.read', 'offer.record', 'evaluation.run',
                         'evaluation.send', 'control.respond', 'communication.register', 'contract.manage', 'order.issue', 'case.close',
                         'supplier.manage', 'framework.select', 'subsanation.manage', 'modification.propose', 'document.upload',
                         'offer.read_confidential', 'ai.extract', 'extraction.review', 'branch.exception', 'branch.restart', 'integration.read'},
    'contaduria': COMMON | {'availability.register', 'budget.manage', 'invoice.register', 'invoice.conform', 'document.upload', 'supplier.manage'},
    'tecnica': COMMON | {'offer.read', 'offer.record', 'requirement.review', 'evaluation.run', 'evaluation.send', 'extraction.review',
                         'ai.extract', 'subsanation.manage', 'document.upload'},
    'comision': COMMON | {'offer.read', 'opinion.register', 'document.upload'},
    'control': COMMON | {'offer.read', 'control.register', 'payment.control', 'document.upload'},
    'ordenador': COMMON | {'offer.read', 'offer.read_confidential', 'call.authorize', 'award.register', 'payment.authorize', 'case.cancel',
                           'branch.deserted', 'branch.reject_offers', 'modification.approve', 'branch.exception', 'branch.restart',
                           'document.upload'},
    'recepcion': COMMON | {'envelope.register', 'receipt.register', 'document.upload'},
    'tesoreria': COMMON | {'payment.record', 'document.upload'},
    'auditor': COMMON | {'offer.read', 'offer.read_confidential', 'audit.read', 'audit.verify', 'integration.read'},
    'administrador': {'normative.read', 'rules.read', 'dashboard.read', 'admin.users', 'admin.areas', 'admin.rules', 'audit.read',
                      'audit.verify', 'integration.read', 'supplier.read', 'case.list_metadata'},
}


def active_assignments(user, at=None):
    at = at or utcnow()
    q = db.select(UserRole).where(UserRole.user_id == user.id, UserRole.revoked_at.is_(None), UserRole.valid_from <= at,
                                  or_(UserRole.valid_to.is_(None), UserRole.valid_to > at))
    return db.session.scalars(q).all()


def _in_scope(assignment, area_id):
    return assignment.area_id is None or area_id is None or assignment.area_id == area_id


def find_assignment(user, perm, area_id=None, assignments=None):
    """Asignación vigente que otorga `perm` para el área dada (None si no existe)."""
    for a in (assignments if assignments is not None else active_assignments(user)):
        if perm in ROLE_PERMS.get(a.role_code, ()) and _in_scope(a, area_id):
            return a
    return None


def has_perm(user, perm, area_id=None):
    return find_assignment(user, perm, area_id) is not None


def user_permissions(user):
    perms, roles = set(), []
    for a in active_assignments(user):
        perms |= ROLE_PERMS.get(a.role_code, set())
        roles.append({'id': a.id, 'role': a.role_code, 'name': ROLE_NAMES.get(a.role_code, a.role_code), 'area_id': a.area_id,
                      'valid_to': a.valid_to.isoformat() if a.valid_to else None,
                      'max_amount': str(a.max_amount) if a.max_amount is not None else None})
    return sorted(perms), roles
