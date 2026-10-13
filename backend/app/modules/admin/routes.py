"""Administración: usuarios, áreas, asignaciones con competencia, segregación, reglas y feriados.

El administrador gestiona accesos y configuración; su cuenta no adquiere competencia para adjudicar, autorizar ni pagar.
"""
import secrets
import string
from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, jsonify, request
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.infrastructure import audit
from app.infrastructure.models import User, UserRole, Area, SegregationRule, RuleSet, RuleParameter, Holiday
from app.modules.identity.permissions import ROLE_NAMES, active_assignments, find_assignment
from app.modules.identity.service import perm_required, validate_password
from app.modules.procurement import inputs as inp
from app.shared.contracts import utcnow, dstr, iso_utc
from app.shared.errors import ApiError, require

bp = Blueprint('admin', __name__, url_prefix='/api/v1/admin')
ALPHABET = string.ascii_letters + string.digits + '!@#$%^&*-_'


def temp_password():
    while True:
        p = ''.join(secrets.choice(ALPHABET) for _ in range(18))
        try:
            validate_password(p)
            return p
        except ApiError:
            continue


def _log(action, rtype, rid, reason=None, details=None):
    a = find_assignment(current_user, 'admin.users')
    audit.record(current_user, action, rtype, rid, reason=reason, details=details, role_code=a.role_code if a else None, assignment_id=a.id if a else None)


def assignment_json(a):
    return {'id': a.id, 'role': a.role_code, 'role_name': ROLE_NAMES.get(a.role_code), 'area_id': a.area_id, 'valid_from': iso_utc(a.valid_from), 'valid_to': iso_utc(a.valid_to),
            'max_amount': dstr(a.max_amount) if a.max_amount is not None else None, 'procedures': a.procedures, 'legal_basis': a.legal_basis, 'revoked': a.revoked_at is not None,
            'delegated_from_id': a.delegated_from_id}


def user_json(u):
    rows = db.session.scalars(db.select(UserRole).where(UserRole.user_id == u.id).order_by(UserRole.id)).all()
    return {'id': u.id, 'username': u.username, 'email': u.email, 'full_name': u.full_name, 'active': u.is_active, 'area_id': u.area_id, 'is_demo': u.is_demo,
            'locked': bool(u.locked_until and u.locked_until > utcnow()), 'last_login_at': iso_utc(u.last_login_at), 'assignments': [assignment_json(a) for a in rows]}


@bp.get('/users')
@perm_required('admin.users')
def users():
    return jsonify(items=[user_json(u) for u in db.session.scalars(db.select(User).order_by(User.full_name))],
                   roles=[{'code': c, 'name': n} for c, n in ROLE_NAMES.items()])


@bp.post('/users')
@perm_required('admin.users')
def create_user():
    data = request.get_json(silent=True) or {}
    username = inp.text(data, 'username', 'Usuario', 3, 64)
    email = inp.text(data, 'email', 'Correo', 5, 120).lower()
    require('@' in email and '.' in email.split('@')[-1], 'validation', 'Correo inválido.', 422, {'email': 'Correo inválido.'})
    pw = temp_password()
    u = User(username=username, email=email, full_name=inp.text(data, 'full_name', 'Nombre', 3, 120), area_id=inp.integer(data, 'area_id', 'Área', required=False, minimum=1),
             must_change_password=True)
    u.set_password(pw)
    db.session.add(u)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise ApiError('duplicate_user', 'Ya existe un usuario con ese nombre o correo.', 409)
    _log('admin.user_create', 'user', u.id, reason=u.username)
    db.session.commit()
    return jsonify(user=user_json(u), temporary_password=pw, notice='Contraseña temporal mostrada una sola vez; deberá cambiarse en el primer ingreso.'), 201


@bp.patch('/users/<int:uid>')
@perm_required('admin.users')
def update_user(uid):
    u = db.session.get(User, uid)
    require(u is not None, 'not_found', 'Usuario no encontrado.', 404)
    data = request.get_json(silent=True) or {}
    require(u.id != current_user.id or data.get('active', True), 'validation', 'No podés desactivar tu propia cuenta.', 422)
    out = {}
    if 'active' in data:
        u.is_active_flag = bool(data['active'])
        u.auth_epoch += 1
    if 'full_name' in data:
        u.full_name = inp.text(data, 'full_name', 'Nombre', 3, 120)
    if 'area_id' in data:
        u.area_id = inp.integer(data, 'area_id', 'Área', required=False, minimum=1)
    if data.get('reset_password'):
        pw = temp_password()
        u.set_password(pw)
        u.must_change_password, u.auth_epoch, u.locked_until, u.failed_logins = True, u.auth_epoch + 1, None, 0
        out['temporary_password'] = pw
    if data.get('unlock'):
        u.locked_until, u.failed_logins = None, 0
    u.updated_at = utcnow()
    _log('admin.user_update', 'user', u.id, details={k: v for k, v in data.items() if k not in ('password',)})
    db.session.commit()
    return jsonify(user=user_json(u), **out)


@bp.post('/users/<int:uid>/assignments')
@perm_required('admin.users')
def add_assignment(uid):
    u = db.session.get(User, uid)
    require(u is not None, 'not_found', 'Usuario no encontrado.', 404)
    data = request.get_json(silent=True) or {}
    role = inp.choice(data, 'role', 'Rol', tuple(ROLE_NAMES))
    area_id = inp.integer(data, 'area_id', 'Área', required=False, minimum=1)
    require(area_id is None or db.session.get(Area, area_id) is not None, 'validation', 'Área inválida.', 422, {'area_id': 'Inválida.'})
    require(role != 'solicitante' or area_id, 'validation', 'El rol Solicitante requiere un área.', 422, {'area_id': 'Obligatoria.'})
    competence_roles = ('ordenador',)
    basis = inp.text(data, 'legal_basis', 'Resolución o delegación que respalda la competencia', 5, 255, required=role in competence_roles)
    valid_from = inp.moment(data, 'valid_from', 'Vigente desde', required=False, default=utcnow())
    valid_to = inp.moment(data, 'valid_to', 'Vigente hasta', required=False)
    require(valid_to is None or valid_to > valid_from, 'validation', 'La vigencia debe terminar después de comenzar.', 422, {'valid_to': 'Inválida.'})
    procedures = data.get('procedures')
    require(procedures is None or (isinstance(procedures, list) and all(isinstance(p, str) for p in procedures)), 'validation', 'Procedimientos inválidos.', 422)
    a = UserRole(user_id=u.id, role_code=role, area_id=area_id, valid_from=valid_from, valid_to=valid_to, procedures=procedures or None, legal_basis=basis,
                 max_amount=inp.decimal(data, 'max_amount', 'Tope de competencia', required=False, places=2), created_by=current_user.id,
                 delegated_from_id=inp.integer(data, 'delegated_from_id', 'Delegante', required=False, minimum=1))
    db.session.add(a)
    u.auth_epoch += 1
    db.session.flush()
    _log('admin.assignment_add', 'user_role', a.id, reason=f'{role} → {u.username}', details=assignment_json(a))
    db.session.commit()
    return jsonify(user=user_json(u)), 201


@bp.post('/assignments/<int:aid>/revoke')
@perm_required('admin.users')
def revoke(aid):
    a = db.session.get(UserRole, aid)
    require(a is not None and a.revoked_at is None, 'not_found', 'Asignación no encontrada o ya revocada.', 404)
    a.revoked_at, a.revoked_by = utcnow(), current_user.id
    db.session.get(User, a.user_id).auth_epoch += 1
    _log('admin.assignment_revoke', 'user_role', a.id, reason=(request.get_json(silent=True) or {}).get('reason'))
    db.session.commit()
    return jsonify(user=user_json(db.session.get(User, a.user_id)))


@bp.post('/areas')
@perm_required('admin.areas')
def create_area():
    data = request.get_json(silent=True) or {}
    area = Area(code=inp.text(data, 'code', 'Código', 2, 30).upper(), name=inp.text(data, 'name', 'Nombre', 3, 120))
    db.session.add(area)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise ApiError('duplicate_area', 'Ya existe un área con ese código.', 409)
    _log('admin.area_create', 'area', area.id, reason=area.name)
    db.session.commit()
    return jsonify({'id': area.id, 'code': area.code, 'name': area.name}), 201


@bp.get('/segregation')
@perm_required('admin.users')
def segregation():
    return jsonify(items=[{'id': r.id, 'action_a': r.action_a, 'action_b': r.action_b, 'active': r.active, 'reason': r.reason} for r in db.session.scalars(db.select(SegregationRule))])


@bp.patch('/segregation/<int:rid>')
@perm_required('admin.users')
def toggle_segregation(rid):
    r = db.session.get(SegregationRule, rid)
    require(r is not None, 'not_found', 'Regla no encontrada.', 404)
    data = request.get_json(silent=True) or {}
    r.active = bool(data.get('active'))
    _log('admin.segregation_toggle', 'segregation_rule', r.id, reason=inp.text(data, 'reason', 'Motivo', 10, 500), details={'active': r.active, 'pair': [r.action_a, r.action_b]})
    db.session.commit()
    return jsonify(ok=True)


@bp.post('/rule-sets')
@perm_required('admin.rules')
def create_rule_set():
    data = request.get_json(silent=True) or {}
    rs = RuleSet(code=inp.text(data, 'code', 'Código', 3, 60), name=inp.text(data, 'name', 'Nombre', 3, 200), jurisdiction=inp.text(data, 'jurisdiction', 'Ámbito', 3, 80),
                 valid_from=inp.day(data, 'valid_from', 'Vigente desde'), valid_to=inp.day(data, 'valid_to', 'Vigente hasta', required=False), status='draft',
                 source_refs=data.get('source_refs') or [])
    db.session.add(rs)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise ApiError('duplicate_rule_set', 'Ya existe un conjunto con ese código.', 409)
    params = data.get('parameters')
    require(isinstance(params, list) and params, 'validation', 'Cargá los parámetros del conjunto.', 422)
    for p in params:
        db.session.add(RuleParameter(rule_set_id=rs.id, key=inp.text(p, 'key', 'Parámetro', 2, 60), value=inp.decimal(p, 'value', 'Valor', positive=False, places=4),
                                     comparator=inp.choice(p, 'comparator', 'Comparador', ('lte', 'lt', 'gt', 'gte')), source_id=inp.text(p, 'source', 'Fuente', 2, 20, required=False),
                                     note=inp.text(p, 'note', 'Nota', 1, 300, required=False)))
    _log('admin.ruleset_create', 'rule_set', rs.id, reason=rs.code)
    db.session.commit()
    return jsonify(code=rs.code, status=rs.status), 201


@bp.post('/rule-sets/<code>/activate')
@perm_required('admin.rules')
def activate_rule_set(code):
    rs = db.session.scalar(db.select(RuleSet).where(RuleSet.code == code).with_for_update())
    require(rs is not None, 'not_found', 'Conjunto no encontrado.', 404)
    data = request.get_json(silent=True) or {}
    note = inp.text(data, 'validation_note', 'Constancia de verificación contra la fuente oficial', 20, 500)
    keys = {p.key for p in db.session.scalars(db.select(RuleParameter).where(RuleParameter.rule_set_id == rs.id))}
    from app.modules.rules.service import PARAMS_2026
    missing = [k for k, *_ in PARAMS_2026 if k not in keys]
    require(not missing, 'validation', f'Faltan parámetros obligatorios: {", ".join(missing)}.', 422)
    for other in db.session.scalars(db.select(RuleSet).where(RuleSet.status == 'active', RuleSet.jurisdiction == rs.jurisdiction, RuleSet.id != rs.id)):
        other.status = 'retired'
    rs.status, rs.validation_note, rs.validated_by, rs.validated_at = 'active', note, current_user.id, utcnow()
    _log('admin.ruleset_activate', 'rule_set', rs.id, reason=note)
    db.session.commit()
    return jsonify(code=rs.code, status=rs.status)


@bp.post('/holidays')
@perm_required('admin.rules')
def add_holiday():
    data = request.get_json(silent=True) or {}
    day = inp.day(data, 'day', 'Fecha')
    if not db.session.get(Holiday, day):
        db.session.add(Holiday(day=day, name=inp.text(data, 'name', 'Nombre', 3, 120)))
    _log('admin.holiday_add', 'holiday', str(day))
    db.session.commit()
    return jsonify(ok=True), 201
