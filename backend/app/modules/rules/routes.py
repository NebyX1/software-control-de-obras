"""Reglas vigentes, orientación por monto, calendario y catálogo normativo."""
from flask import Blueprint, jsonify, request
from flask_login import current_user
from app.extensions import db
from app.infrastructure.models import RuleSet, NormativeSource, Holiday
from app.modules.identity.service import perm_required
from app.modules.rules import service as rules
from app.shared.contracts import dstr, to_decimal
from app.shared.errors import ApiError, require

bp = Blueprint('rules', __name__, url_prefix='/api/v1')


def rule_set_json(rs):
    params = rules.parameters(rs)
    return {'code': rs.code, 'name': rs.name, 'jurisdiction': rs.jurisdiction, 'valid_from': rs.valid_from.isoformat(), 'valid_to': rs.valid_to.isoformat() if rs.valid_to else None,
            'status': rs.status, 'source_refs': rs.source_refs, 'validation_note': rs.validation_note,
            'parameters': [{'key': k, 'value': dstr(p.value), 'comparator': p.comparator, 'unit': p.unit, 'source': p.source_id, 'note': p.note} for k, p in sorted(params.items())]}


@bp.get('/rules')
@perm_required('rules.read')
def current_rules():
    sets = db.session.scalars(db.select(RuleSet).order_by(RuleSet.valid_from.desc())).all()
    active = rules.active_rule_set()
    return jsonify(active=rule_set_json(active) if active else None, versions=[{'code': s.code, 'status': s.status, 'valid_from': s.valid_from.isoformat()} for s in sets],
                   notice='Los montos se actualizan anualmente y deben contrastarse con la fuente oficial vigente. No se activaron los topes ampliados del art. 44.')


@bp.get('/rules/suggest')
@perm_required('rules.read')
def suggest():
    try:
        amount = to_decimal(request.args.get('amount'), 'amount', places=2)
    except ApiError:
        raise ApiError('validation', 'Ingresá un importe válido, sin separador de miles.', 422)
    return jsonify(rules.suggest_procedure(amount))


@bp.get('/normative/sources')
@perm_required('normative.read')
def sources():
    q = (request.args.get('q') or '').strip()
    query = db.select(NormativeSource).order_by(NormativeSource.code)
    if q:
        like = f'%{q[:80]}%'
        query = query.where(NormativeSource.titulo.like(like) | NormativeSource.hallazgo.like(like) | NormativeSource.organismo.like(like) | NormativeSource.code.like(like))
    return jsonify(items=[{'code': s.code, 'organismo': s.organismo, 'titulo': s.titulo, 'url': s.url, 'consulta': s.consulta.isoformat(), 'hallazgo': s.hallazgo, 'tipo': s.tipo,
                           'scope': s.scope, 'kind': s.kind, 'validation_status': s.validation_status} for s in db.session.scalars(query)],
                   notice='Catálogo de fuentes. Su inclusión no implica validación jurídica; el informe de investigación es un documento de diseño, no una norma.')
