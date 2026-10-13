"""Rutas de IA: consulta con fuentes (SSE), extracción asistida, revisión de campos, explicación, borradores e inconsistencias."""
from flask import Blueprint, Response, jsonify, request, stream_with_context
from flask_login import current_user
from app.extensions import db
from app.infrastructure import audit, tasks
from app.infrastructure.models import (BackgroundTask, Document, DocumentVersion, ExtractedField, FieldReview, Offer, AiDraft, Evaluation, ProcurementCase)
from app.ai import assist, chat as chat_mod, client, schemas
from app.modules.documents.policies import can_read_content
from app.modules.evaluation import service as evals
from app.modules.identity.permissions import find_assignment
from app.modules.identity.service import auth_required, perm_required, rate_limit
from app.modules.procurement import framework, inputs as inp
from app.modules.procurement.access import get_case
from app.shared.errors import ApiError, require

bp = Blueprint('ai', __name__, url_prefix='/api/v1/ai')


def _unavailable(exc):
    return ApiError('ai_unavailable', str(exc), 503, extra={'provider_code': exc.code, 'degraded': True})


@bp.post('/chat/stream')
@perm_required('ai.use')
def chat_stream():
    rate_limit('ai-chat', 20)
    data = request.get_json(silent=True) or {}
    scope = inp.choice(data, 'scope', 'Ámbito', ('case', 'normative'))
    message = inp.text(data, 'message', 'Consulta', 3, chat_mod.MAX_MSG)
    case, facts = None, None
    if scope == 'case':
        case = get_case(current_user, inp.text(data, 'case_code', 'Expediente', 3, 20))
        facts = assist.case_facts(current_user, case)
    else:
        require(find_assignment(current_user, 'normative.read'), 'forbidden', 'Sin permiso para consultar la normativa.', 403)
    user = current_user._get_current_object()
    headers = {'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Content-Type': 'text/event-stream; charset=utf-8'}
    return Response(stream_with_context(chat_mod.stream_answer(user, case, scope, message, facts)), headers=headers)


# ---------------------------------------------------------------- extracción asistida

def _task_json(t):
    return {'id': t.id, 'kind': t.kind, 'status': t.status, 'attempts': t.attempts, 'error': t.last_error, 'result': t.result, 'created_at': t.created_at.isoformat() if t.created_at else None}


@bp.post('/cases/<code>/extract')
@perm_required('ai.extract')
def extract(code):
    rate_limit('ai-extract', 10)
    case = get_case(current_user, code)
    require(find_assignment(current_user, 'ai.extract', case.area_id), 'forbidden', 'Sin permiso para la extracción asistida.', 403)
    data = request.get_json(silent=True) or {}
    offer = db.session.get(Offer, inp.integer(data, 'offer_id', 'Oferta', minimum=1))
    require(offer is not None and offer.case_id == case.id, 'not_found', 'Oferta no encontrada.', 404)
    doc = db.session.get(Document, inp.integer(data, 'document_id', 'Documento', minimum=1))
    require(doc is not None and doc.case_id == case.id, 'not_found', 'Documento no encontrado.', 404)
    if not can_read_content(current_user, doc, case):
        raise ApiError('not_found', 'Documento no disponible.', 404)  # reservado/confidencial/sin permiso: no se distingue
    ver = db.session.scalar(db.select(DocumentVersion).where(DocumentVersion.document_id == doc.id).order_by(DocumentVersion.version.desc()))
    require(ver is not None and ver.text_status == 'extracted', 'no_text', 'El documento no tiene texto extraído: queda pendiente de tratamiento manual.', 409)
    try:
        client.check_ready()
    except client.ProviderError as exc:
        raise _unavailable(exc)
    # El mismo (usuario, versión, oferta) reutiliza la tarea: recargar la página no genera llamadas duplicadas.
    key = f'extract:{current_user.id}:{ver.id}:{offer.id}'
    existing = db.session.scalar(db.select(BackgroundTask).where(BackgroundTask.dedupe_key == key))
    if existing and existing.status in ('queued', 'running', 'succeeded'):
        return jsonify(_task_json(existing)), 200
    if existing:
        db.session.delete(existing)
        db.session.flush()
    task = tasks.enqueue('ai_extract', {'document_version_id': ver.id, 'offer_id': offer.id, 'user_id': current_user.id}, case_id=case.id, user_id=current_user.id, dedupe_key=key, max_attempts=2)
    a = find_assignment(current_user, 'ai.extract', case.area_id)
    audit.record(current_user, 'ai.extract_requested', 'document', doc.id, case=case, reason='Extracción asistida solicitada', details={'offer_id': offer.id, 'version_id': ver.id},
                 role_code=a.role_code if a else None, assignment_id=a.id if a else None)
    db.session.commit()
    return jsonify(_task_json(task)), 202


@bp.get('/tasks/<int:task_id>')
@auth_required
def task_status(task_id):
    t = db.session.get(BackgroundTask, task_id)
    if not t or t.created_by != current_user.id:
        raise ApiError('not_found', 'Tarea no encontrada.', 404)
    return jsonify(_task_json(t))


def _field_json(f):
    review = db.session.scalar(db.select(FieldReview).where(FieldReview.field_id == f.id).order_by(FieldReview.id.desc()))
    return {'id': f.id, 'offer_id': f.offer_id, 'document_version_id': f.document_version_id, 'key': f.field_key, 'proposed_value': f.proposed_value, 'page': f.page, 'quote': f.quote,
            'evidence_verified': f.evidence_verified, 'status': f.status, 'model': f.model,
            'final_value': review.value if review and review.value else f.proposed_value if f.status in ('confirmed',) else None,
            'review': None if not review else {'action': review.action, 'note': review.note, 'at': review.created_at.isoformat() if review.created_at else None}}


@bp.get('/cases/<code>/fields')
@perm_required('extraction.review')
def fields(code):
    case = get_case(current_user, code)
    q = (db.select(ExtractedField).join(Offer, Offer.id == ExtractedField.offer_id).where(Offer.case_id == case.id).order_by(ExtractedField.id.desc()))
    if request.args.get('offer_id', type=int):
        q = q.where(ExtractedField.offer_id == request.args.get('offer_id', type=int))
    docs = {d.id: d for d in db.session.scalars(db.select(Document).where(Document.case_id == case.id))}
    out = []
    for f in db.session.scalars(q.limit(300)):  # solo campos de documentos que el usuario puede leer hoy
        ver = db.session.get(DocumentVersion, f.document_version_id)
        if can_read_content(current_user, docs[ver.document_id], case):
            out.append(_field_json(f))
    return jsonify(items=out, notice='Campos propuestos por IA: no son datos validados hasta que una persona los revise.')


@bp.post('/fields/<int:field_id>/review')
@perm_required('extraction.review')
def review_field(field_id):
    f = db.session.get(ExtractedField, field_id)
    offer = db.session.get(Offer, f.offer_id) if f else None
    case = db.session.get(ProcurementCase, offer.case_id) if offer else None
    if not f or not case:
        raise ApiError('not_found', 'Campo no encontrado.', 404)
    case = get_case(current_user, case.code)
    ver = db.session.get(DocumentVersion, f.document_version_id)
    if not can_read_content(current_user, db.session.get(Document, ver.document_id), case):
        raise ApiError('not_found', 'Campo no encontrado.', 404)
    a = find_assignment(current_user, 'extraction.review', case.area_id)
    require(a is not None, 'forbidden', 'Sin permiso para revisar campos.', 403)
    data = request.get_json(silent=True) or {}
    action = inp.choice(data, 'action', 'Acción', ('confirm', 'correct', 'reject'))
    value = inp.text(data, 'value', 'Valor corregido', 1, 200, required=action == 'correct')
    note = inp.text(data, 'note', 'Nota', 3, 500, required=action != 'confirm', default=None)
    f.status = {'confirm': 'confirmed', 'correct': 'corrected', 'reject': 'rejected'}[action]
    db.session.add(FieldReview(field_id=f.id, action=action, value=value if action == 'correct' else f.proposed_value, note=note, reviewer_id=current_user.id))
    audit.record(current_user, 'extraction.review', 'extracted_field', f.id, case=case, reason=note or 'Campo confirmado', reference=f.field_key,
                 details={'action': action, 'proposed': f.proposed_value, 'final': value if action == 'correct' else f.proposed_value, 'page': f.page, 'offer_id': f.offer_id},
                 role_code=a.role_code, assignment_id=a.id)
    db.session.commit()
    return jsonify(_field_json(f))


# ---------------------------------------------------------------- explicación, borradores, inconsistencias

def _current_ev(case):
    ev = evals.current_evaluation(case.id)
    require(ev is not None, 'not_found', 'No hay una evaluación vigente.', 404)
    return ev


def _draft_flow(code, kind, instruction):
    rate_limit('ai-draft', 10)
    case = get_case(current_user, code)
    require(find_assignment(current_user, 'ai.use', case.area_id) and find_assignment(current_user, 'evaluation.read', case.area_id), 'forbidden', 'Sin permiso.', 403)
    ev = _current_ev(case)
    force = request.args.get('force') == '1'
    existing = db.session.scalar(db.select(AiDraft).where(AiDraft.case_id == case.id, AiDraft.kind == kind, AiDraft.evaluation_id == ev.id).order_by(AiDraft.id.desc()))
    if existing and not force:
        return jsonify(assist.draft_json(existing))  # evita llamadas duplicadas por recargar la página
    try:
        draft, _ = assist.generate_text(current_user, case, kind, instruction, assist.rules_explanation_json(ev), ev)
    except client.ProviderError as exc:
        raise _unavailable(exc)
    except Exception as exc:
        if exc.__class__.__name__ == 'EgressBlocked':
            raise ApiError('egress_blocked', str(exc), 403)
        raise
    return jsonify(assist.draft_json(draft)), 201


@bp.post('/cases/<code>/explain')
@auth_required
def explain_with_ai(code):
    return _draft_flow(code, 'explicacion', 'Explicá en lenguaje claro por qué el cálculo arroja esta recomendación, qué ofertas quedaron fuera y por qué, y qué debe revisar una persona. Máximo 250 palabras.')


@bp.post('/cases/<code>/draft')
@auth_required
def draft(code):
    kind = (request.get_json(silent=True) or {}).get('kind', 'borrador_dictamen')
    require(kind in ('borrador_dictamen', 'borrador_analisis'), 'validation', 'Tipo de borrador inválido.', 422)
    text = ('Redactá un borrador de dictamen técnico-administrativo, en tercera persona, que resuma criterios, exclusiones y resultado del cálculo. '
            'Dejá entre corchetes los datos que debe completar la comisión. No decidas por ella.' if kind == 'borrador_dictamen' else
            'Redactá un borrador de análisis comparativo de las ofertas, con cuadro textual de importes comparables y observaciones. Máximo 300 palabras.')
    return _draft_flow(code, kind, text)


@bp.get('/cases/<code>/inconsistencies')
@auth_required
def inconsistencies(code):
    case = get_case(current_user, code)
    require(find_assignment(current_user, 'evaluation.read', case.area_id), 'forbidden', 'Sin permiso.', 403)
    ctx = framework.Ctx(case, current_user)
    return jsonify(items=assist.inconsistencies(current_user, case, ctx),
                   notice='Controles deterministas sobre datos validados; no reemplazan la revisión de las personas competentes.')
