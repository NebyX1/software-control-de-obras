"""Marco de acciones del expediente.

Toda transición es una operación explícita del servidor: transacción única, bloqueo de la fila del expediente,
control de versión (`expected_version`), idempotencia (`Idempotency-Key`), permiso y competencia del actor, segregación
de funciones, bloqueos con motivos claros y auditoría encadenada. Desactivar un botón en el navegador no es un control.
"""
from dataclasses import dataclass, field
from typing import Callable, Optional
from sqlalchemy.exc import IntegrityError, OperationalError
from app.extensions import db
from app.infrastructure import audit
from app.infrastructure.models import (ProcurementCase, SegregationRule, AuditEvent, IdempotencyRecord, RequestLine, SpecVersion)
from app.modules.identity.permissions import ROLE_PERMS, ROLE_NAMES, find_assignment, active_assignments
from app.modules.procurement.states import STATUS_STAGE, STATUS_LABEL, NEXT_BY_STATUS
from app.shared.contracts import canonical_hash, utcnow
from app.shared.errors import ApiError

REGISTRY: dict = {}


@dataclass
class Action:
    name: str
    label: str
    perm: str
    states: set
    handler: Callable
    form: Optional[Callable] = None
    blockers: Optional[Callable] = None
    done: Optional[Callable] = None
    competence: bool = False
    description: str = ''
    danger: bool = False
    reason_required: bool = False


def action(name, label, perm, states, form=None, blockers=None, done=None, competence=False, description='', danger=False):
    def deco(fn):
        REGISTRY[name] = Action(name, label, perm, set(states), fn, form, blockers, done, competence, description, danger)
        return fn
    return deco


class Ctx:
    """Contexto de una acción: expediente (bloqueado al ejecutar), actor y consultas frecuentes."""

    def __init__(self, case, user, assignments=None, executing=False):
        self.case, self.user, self.executing = case, user, executing
        self.now = utcnow()
        self.assignments = assignments if assignments is not None else (active_assignments(user) if user is not None else [])
        self._cache = {}

    def assignment(self, perm):
        return find_assignment(self.user, perm, self.case.area_id, self.assignments)

    def memo(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    @property
    def lines(self):
        return self.memo('lines', lambda: db.session.scalars(db.select(RequestLine).where(RequestLine.case_id == self.case.id).order_by(RequestLine.position)).all())

    @property
    def spec(self):
        """Pliego vigente: el de mayor versión no reemplazado."""
        return self.memo('spec', lambda: db.session.scalars(
            db.select(SpecVersion).where(SpecVersion.case_id == self.case.id, SpecVersion.status != 'superseded')
            .order_by(SpecVersion.version.desc())).first())

    def require_competence(self, amount, perm):
        a = self.assignment(perm)
        problem = competence_problem(a, amount, self.case.procedure_type)
        if problem:
            raise ApiError('competence', problem, 403)
        return a


def competence_problem(assignment, amount, procedure_type):
    if assignment is None:
        return 'No tenés una asignación vigente para esta actuación.'
    if not assignment.legal_basis:
        return 'Tu asignación de ordenador no registra la resolución o delegación que respalda la competencia. Un administrador debe completarla.'
    if assignment.max_amount is not None and amount is not None and amount > assignment.max_amount:
        return f'El monto supera el tope de tu competencia vigente ({assignment.max_amount}).'
    if assignment.procedures and procedure_type and procedure_type not in assignment.procedures:
        return 'Tu competencia vigente no alcanza este tipo de procedimiento.'
    return None


def responsible_names(perm):
    return [ROLE_NAMES[r] for r, perms in ROLE_PERMS.items() if perm in perms and r != 'administrador']


def action_blockers(act, ctx):
    return list(act.blockers(ctx)) if act.blockers else []


def action_form(act, ctx):
    if act.form is None:
        return []
    return act.form(ctx) if callable(act.form) else act.form


def available_actions(ctx):
    """Acciones del estado actual, con motivos de bloqueo y formulario. `can` indica si el actor tiene permiso."""
    out = []
    for name, act in REGISTRY.items():
        if ctx.case.status not in act.states:
            continue
        can = ctx.assignment(act.perm) is not None
        out.append({'name': name, 'label': act.label, 'description': act.description, 'responsible': responsible_names(act.perm),
                    'can': can, 'blockers': action_blockers(act, ctx), 'form': action_form(act, ctx) if can else [],
                    'danger': act.danger, 'done': bool(act.done(ctx)) if act.done else False})
    return out


def main_action(ctx, available):
    """Una acción principal por momento: la primera de la secuencia del estado que no está cumplida."""
    by_name = {a['name']: a for a in available}
    for name in NEXT_BY_STATUS.get(ctx.case.status, []):
        a = by_name.get(name)
        if a and not a['done']:
            return a
    return None


def _check_segregation(ctx, act):
    rules = db.session.scalars(db.select(SegregationRule).where(SegregationRule.active.is_(True),
                               (SegregationRule.action_a == act.name) | (SegregationRule.action_b == act.name))).all()
    others = {r.action_b if r.action_a == act.name else r.action_a: r.reason for r in rules}
    if not others:
        return
    done = db.session.scalars(db.select(AuditEvent.action).where(AuditEvent.case_id == ctx.case.id, AuditEvent.actor_id == ctx.user.id,
                                                                  AuditEvent.action.in_(list(others)))).first()
    if done:
        raise ApiError('segregation', 'Segregación de funciones: ' + others[done] + ' Esta actuación debe realizarla otra persona.', 403)


def lock_case(code):
    return db.session.scalar(db.select(ProcurementCase).where(ProcurementCase.code == code).with_for_update().execution_options(populate_existing=True))


def execute(case_code, name, payload, user, expected_version=None, idempotency_key=None):
    """Ejecuta una acción. Debe llamarse con la sesión limpia; confirma o revierte la transacción completa."""
    from app.modules.procurement.access import can_read_case
    act = REGISTRY.get(name)
    if act is None:
        raise ApiError('unknown_action', 'Acción desconocida.', 404)
    payload = payload if isinstance(payload, dict) else {}
    try:
        case = lock_case(case_code)
        if case is None or not can_read_case(user, case):
            raise ApiError('not_found', 'No se encontró el expediente.', 404)
        ctx = Ctx(case, user, executing=True)
        assignment = ctx.assignment(act.perm)
        if assignment is None:
            raise ApiError('forbidden', 'Tu perfil no tiene permiso para esta actuación en este expediente.', 403)
        req_hash = canonical_hash({'action': name, 'payload': payload})
        scope = f'{case.id}:{name}'
        if idempotency_key:
            prev = db.session.scalar(db.select(IdempotencyRecord).where(IdempotencyRecord.actor_id == user.id, IdempotencyRecord.scope == scope,
                                                                        IdempotencyRecord.key == idempotency_key))
            if prev:
                if prev.request_hash != req_hash:
                    raise ApiError('idempotency_conflict', 'La clave de idempotencia ya se usó con otra petición.', 409)
                db.session.rollback()
                return {'replayed': True, 'version': prev.response.get('version')}
        if expected_version is not None and int(expected_version) != case.version:
            raise ApiError('version_conflict', 'Otra persona modificó este expediente. Recargá para ver el estado actual y volvé a intentar.', 409,
                           extra={'current_version': case.version})
        if case.status not in act.states:
            raise ApiError('invalid_state', f'Esta actuación no está disponible cuando el expediente está en “{STATUS_LABEL.get(case.status, case.status)}”.', 409)
        problems = action_blockers(act, ctx)
        if problems:
            raise ApiError('blocked', problems[0], 422, extra={'blockers': problems})
        _check_segregation(ctx, act)
        result = act.handler(ctx, payload) or {}
        case.version += 1
        case.updated_at = utcnow()
        if 'status' in result:
            case.status = result['status']
            if case.status in STATUS_STAGE:
                case.stage = STATUS_STAGE[case.status]
        audit.record(user, name, result.get('type', 'case'), result.get('id', case.id), case=case, reason=result.get('reason'),
                     reference=result.get('reference'), details=result.get('details'), resource_version=case.version,
                     role_code=assignment.role_code, assignment_id=assignment.id)
        if idempotency_key:
            db.session.add(IdempotencyRecord(actor_id=user.id, scope=scope, key=idempotency_key, request_hash=req_hash, status_code=200,
                                             response={'version': case.version}))
        db.session.commit()
        return {'replayed': False, 'version': case.version}
    except IntegrityError as exc:
        db.session.rollback()
        raise _integrity_to_api(exc)
    except OperationalError as exc:
        db.session.rollback()
        if getattr(exc.orig, 'args', [None])[0] in (1213, 1205):  # deadlock / lock wait timeout
            raise ApiError('busy', 'El expediente está siendo modificado por otra operación. Reintentá en unos segundos.', 409)
        raise
    except Exception:
        db.session.rollback()
        raise


def _integrity_to_api(exc):
    msg = str(exc.orig).lower()
    table = {
        'uq_award_active': ('already_awarded', 'Este expediente ya tiene una adjudicación vigente.'),
        'uq_order_award': ('already_ordered', 'Ya existe una orden de compra para esta adjudicación.'),
        'uq_invoice_identity': ('duplicate_invoice', 'Esa factura ya está registrada para el proveedor (mismo tipo, serie y número).'),
        'uq_payment_proof': ('duplicate_payment', 'Ese comprobante de pago ya fue registrado para la factura.'),
        'uq_payment_idem': ('duplicate_payment', 'Ese pago ya fue registrado.'),
        'uq_availability_active': ('duplicate_availability', 'Ya existe una disponibilidad activa para este expediente.'),
        'uq_envelope_supplier': ('duplicate_envelope', 'Ese proveedor ya presentó un sobre en este procedimiento.'),
        'ck_order_line_qty': ('quantity_conflict', 'La operación dejaría cantidades inconsistentes.'),
        'ck_invoice_paid_le_authorized': ('overpayment', 'El pago superaría el importe autorizado.'),
    }
    for key, (code, text) in table.items():
        if key in msg:
            return ApiError(code, text, 409)
    return ApiError('conflict', 'La operación entra en conflicto con datos existentes.', 409)
