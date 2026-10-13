"""Transporte HTTP de expedientes: listados, detalle, acciones, laboratorio y tablero. Sin lógica de negocio."""
import copy
from flask import Blueprint, jsonify, request
from flask_login import current_user
from sqlalchemy import exists, or_, and_, func
from app.extensions import db
from app.infrastructure.models import (ProcurementCase, Intervention, ObservationResponse, Availability, Evaluation, AuditEvent, Area, IdempotencyRecord)
from app.modules.evaluation import service as evals, engine
from app.modules.evaluation.explain import explain
from app.modules.identity.service import auth_required, perm_required, rate_limit
from app.modules.procurement import framework, serializers as S
from app.modules.procurement import actions  # noqa: F401
from app.modules.procurement.access import visible_cases_query, get_case
from app.modules.procurement.service import create_case
from app.modules.procurement.states import STATUS_STAGE, BRANCH_STATUSES, STAGES
from app.shared.contracts import canonical_hash
from app.shared.errors import ApiError, require

bp = Blueprint('procurement', __name__, url_prefix='/api/v1')


def body():
    value = request.get_json(silent=True)
    require(isinstance(value, dict), 'invalid_json', 'Enviá un objeto JSON válido.', 422)
    return value


ACTIVE = [s for s in STATUS_STAGE if s != 'closed']


def _attention_clause():
    c = ProcurementCase
    pending_obs = exists().where(and_(Intervention.case_id == c.id, Intervention.kind == 'control_gasto', Intervention.status == 'active', Intervention.result == 'observado',
                                      ~exists().where(ObservationResponse.intervention_id == Intervention.id)))
    no_av = and_(c.status == 'preparation', ~exists().where(and_(Availability.case_id == c.id, Availability.status == 'active')))
    stale = exists().where(and_(Evaluation.case_id == c.id, Evaluation.status == 'stale'))
    return and_(c.status.in_(ACTIVE), or_(pending_obs, no_av, stale))


@bp.get('/cases')
@auth_required
def list_cases():
    q = visible_cases_query(current_user)
    c = ProcurementCase
    search = (request.args.get('q') or '').strip()
    if search:
        like = f'%{search.replace("%", "").replace("_", "")[:80]}%'
        q = q.outerjoin(Area, Area.id == c.area_id).where(or_(c.code.like(like), c.title.like(like), Area.name.like(like)))
    flt = request.args.get('filter', 'all')
    if flt == 'active':
        q = q.where(c.status.in_(ACTIVE))
    elif flt == 'attention':
        q = q.where(_attention_clause())
    elif flt == 'closed':
        q = q.where(c.status == 'closed')
    elif flt not in ('all', ''):
        raise ApiError('validation', 'Filtro inválido.', 422)
    if request.args.get('stage') not in (None, ''):
        try:
            q = q.where(c.stage == int(request.args['stage']))
        except ValueError:
            raise ApiError('validation', 'Etapa inválida.', 422)
    total = db.session.scalar(db.select(func.count()).select_from(q.order_by(None).subquery()))
    sort = {'updated': c.updated_at.desc(), 'code': c.code.desc(), 'amount': c.estimated_total.desc(), 'created': c.created_at.desc()}.get(request.args.get('sort', 'updated'))
    require(sort is not None, 'validation', 'Orden inválido.', 422)
    try:
        page, per = max(1, int(request.args.get('page', 1))), min(100, max(1, int(request.args.get('per_page', 20))))
    except ValueError:
        raise ApiError('validation', 'Paginación inválida.', 422)
    rows = db.session.scalars(q.order_by(sort, c.id.desc()).limit(per).offset((page - 1) * per)).all()
    return jsonify(items=[S.case_summary(r) for r in rows], total=total, page=page, per_page=per)


@bp.post('/cases')
@perm_required('case.create')
def create():
    rate_limit('case-create', 30)
    data = body()
    key = request.headers.get('Idempotency-Key')
    if key:
        h = canonical_hash(data)
        prev = db.session.scalar(db.select(IdempotencyRecord).where(IdempotencyRecord.actor_id == current_user.id, IdempotencyRecord.scope == 'case.create', IdempotencyRecord.key == key))
        if prev:
            require(prev.request_hash == h, 'idempotency_conflict', 'La clave de idempotencia ya se usó con otra petición.', 409)
            return jsonify(S.case_detail(current_user, get_case(current_user, prev.response['code']))), 200
    case = create_case(current_user, data)
    if key:
        db.session.add(IdempotencyRecord(actor_id=current_user.id, scope='case.create', key=key, request_hash=canonical_hash(data), status_code=201, response={'code': case.code}))
    db.session.commit()
    return jsonify(S.case_detail(current_user, case)), 201


@bp.get('/cases/<code>')
@auth_required
def detail(code):
    return jsonify(S.case_detail(current_user, get_case(current_user, code)))


@bp.post('/cases/<code>/actions/<name>')
@auth_required
def run_action(code, name):
    rate_limit('action', 120)
    data = body()
    expected = data.pop('expected_version', None)
    require(expected is None or isinstance(expected, int), 'validation', 'expected_version inválido.', 422)
    key = request.headers.get('Idempotency-Key') or data.pop('idempotency_key', None)
    require(key is None or (isinstance(key, str) and 8 <= len(key) <= 80), 'validation', 'La clave de idempotencia debe tener entre 8 y 80 caracteres.', 422)
    result = framework.execute(code, name, data, current_user, expected, key)
    db.session.remove()
    case = get_case(current_user, code)
    out = S.case_detail(current_user, case)
    out['replayed'] = result['replayed']
    return jsonify(out)


@bp.get('/cases/<code>/events')
@auth_required
def events(code):
    case = get_case(current_user, code)
    before = request.args.get('before', type=int)
    return jsonify(items=S.events_json(case.id, min(100, request.args.get('limit', 50, type=int)), before_id=before))


@bp.get('/cases/<code>/explanation')
@perm_required('evaluation.read')
def explanation(code):
    case = get_case(current_user, code)
    ev = evals.current_evaluation(case.id)
    require(ev is not None, 'not_found', 'No hay una evaluación vigente para explicar.', 404)
    return jsonify(explain(ev.result))


@bp.post('/cases/<code>/evaluation/scenario')
@perm_required('evaluation.read')
def scenario(code):
    """Laboratorio: copia aislada. Nunca persiste ni modifica ofertas, evaluaciones ni dictámenes."""
    rate_limit('scenario', 60)
    case = get_case(current_user, code)
    ctx = framework.Ctx(case, current_user)
    require(ctx.spec is not None and ctx.spec.status == 'approved', 'blocked', 'El pliego debe estar aprobado.', 422)
    data = body()
    inp, _ = evals.preview(case, ctx.spec, ctx.lines)
    inp = copy.deepcopy({k: v for k, v in inp.items() if k != 'traceability'})
    for ov in data.get('overrides', []):
        offer = next((o for o in inp['offers'] if o['id'] == ov.get('offer_id')), None)
        require(offer is not None, 'validation', 'Oferta inválida en el escenario.', 422)
        for line in offer['lines']:
            if ov.get('unit_price') is not None:
                line['unit_price'] = str(ov['unit_price'])
        for k in ('delivery_days', 'warranty_months'):
            if ov.get(k) is not None:
                offer['attributes'][k] = int(ov[k])
        if ov.get('freight') is not None:
            offer['freight'] = str(ov['freight'])
        for req_id, res in (ov.get('reviews') or {}).items():
            require(res in ('met', 'not_met'), 'validation', 'Revisión inválida.', 422)
            offer['reviews'][str(req_id)] = {'result': res}
    try:
        result = engine.evaluate(inp)
    except engine.EngineInputError as exc:
        raise ApiError('validation', str(exc), 422)
    return jsonify(result=result, isolated=True, note='Copia aislada: no se modificó ninguna oferta, evaluación ni dictamen.')


@bp.get('/dashboard')
@perm_required('dashboard.read')
def dashboard():
    q = visible_cases_query(current_user)
    c = ProcurementCase
    sub = q.order_by(None).subquery()
    active = db.session.scalar(db.select(func.count()).select_from(sub).where(sub.c.status.in_(ACTIVE)))
    total = db.session.scalar(db.select(func.count()).select_from(sub))
    ready = db.session.scalar(db.select(func.count()).select_from(sub).where(sub.c.status.in_(('offers_opened', 'evaluation'))))
    attention = db.session.scalar(db.select(func.count()).select_from(q.where(_attention_clause()).order_by(None).subquery()))
    ids = [r for r in db.session.scalars(q.with_only_columns(c.id).order_by(None))]
    events = db.session.scalar(db.select(func.count(AuditEvent.id)).where(AuditEvent.case_id.in_(ids or [0])))
    recent = db.session.scalars(db.select(AuditEvent).where(AuditEvent.case_id.in_(ids or [0])).order_by(AuditEvent.id.desc()).limit(4)).all()
    codes = {r.id: r.code for r in db.session.scalars(db.select(c).where(c.id.in_([e.case_id for e in recent] or [0])))}
    top = db.session.scalars(q.order_by(c.updated_at.desc()).limit(5)).all()
    return jsonify(stats={'active': active, 'total': total, 'ready_to_compare': ready, 'attention': attention, 'events': events},
                   recent=[{**S.event_json(e), 'case': codes.get(e.case_id)} for e in recent], cases=[S.case_summary(r) for r in top], stages=STAGES)
