"""Etapas 4 y 5 (Evaluación y Decisión): evaluación versionada, dictamen, control preventivo, adjudicación."""
from datetime import date
from decimal import Decimal
from app.extensions import db
from app.infrastructure.models import (Opinion, Intervention, ObservationResponse, Award, AwardLine, Offer, SupplierStatus, OfferDataVersion, Availability)
from app.modules.evaluation import service as evals
from app.modules.procurement import forms as F, inputs as inp
from app.modules.procurement.actions.common import doc_in_case
from app.modules.procurement.framework import action
from app.modules.rules.service import suggest_procedure
from app.shared.contracts import dstr
from app.shared.errors import ApiError, require


def current_ev(ctx):
    return evals.current_evaluation(ctx.case.id)


def commission_required(case):
    if case.currency != 'UYU':
        return False
    try:
        return suggest_procedure(case.estimated_total)['flags']['comision_asesora_obligatoria'] and case.procedure_type in ('concurso_precios', 'licitacion_abreviada', 'licitacion_publica')
    except ApiError:
        return False


def pending_observation(case_id):
    last = db.session.scalar(db.select(Intervention).where(Intervention.case_id == case_id, Intervention.kind == 'control_gasto', Intervention.status == 'active')
                             .order_by(Intervention.id.desc()))
    if last and last.result == 'observado' and not db.session.scalar(db.select(ObservationResponse.id).where(ObservationResponse.intervention_id == last.id)):
        return last
    return None


def _offers_in_eval(ev):
    return {o['id']: o for o in ev.result['offers']}


# ---------------------------------------------------------------- evaluación

def _run_blockers(ctx):
    if not ctx.spec or ctx.spec.status != 'approved':
        return ['El pliego debe estar aprobado.']
    return []


@action('evaluation.run', 'Calcular la evaluación', 'evaluation.run', {'offers_opened', 'evaluation', 'decision'}, blockers=_run_blockers,
        form=lambda ctx: [F.field('reason', 'Motivo del cálculo', 'textarea', rows=2, required=False)],
        description='Aplica requisitos y criterios del pliego a datos validados. Cada cálculo guarda entradas exactas, versiones y resultado.')
def evaluation_run(ctx, data):
    prev = current_ev(ctx)
    if ctx.case.status == 'decision':
        evals.mark_dependents_stale(ctx.case, 'Se recalculó la evaluación.')
    ev = evals.persist(ctx.case, ctx.spec, ctx.lines, ctx.user)
    result = {'type': 'evaluation', 'id': ev.id, 'reference': f'EV-{ctx.case.code}-v{ev.version}',
              'reason': 'Evaluación calculada. ' + ('Recomendación: oferta %s.' % ev.recommended_offer_id if ev.recommended_offer_id else 'Sin recomendación: ' + '; '.join(ev.result['blocked_reasons'])),
              'details': {'version': ev.version, 'status': ev.result['status'], 'input_hash': ev.input_hash, 'previous': prev.version if prev else None}}
    if ctx.case.status == 'offers_opened':
        result['status'] = 'evaluation'
    return result


def _send_blockers(ctx):
    ev = current_ev(ctx)
    if ev is None:
        return ['Calculá la evaluación.']
    if ev.result['status'] != 'recommended':
        return ['La evaluación no tiene recomendación: ' + ' '.join(ev.result['blocked_reasons'])]
    return []


@action('evaluation.send', 'Enviar a decisión y control', 'evaluation.send', {'evaluation'}, blockers=_send_blockers,
        form=lambda ctx: F.ref_reason('Fundamento del envío', 'Referencia del envío'),
        description='El envío no adjudica ni notifica proveedores: abre la intervención de comisión, control y ordenador.')
def evaluation_send(ctx, data):
    ev = current_ev(ctx)
    return {'status': 'decision', 'type': 'evaluation', 'id': ev.id, 'reference': inp.text(data, 'reference', 'Referencia', 2, 200),
            'reason': inp.text(data, 'reason', 'Fundamento', 5, 1000), 'details': {'version': ev.version}}


# ---------------------------------------------------------------- dictamen

def _opinion_blockers(ctx):
    ev = current_ev(ctx)
    if ev is None:
        return ['La evaluación vigente fue invalidada: recalculala antes de dictaminar.']
    if ev.result['status'] != 'recommended':
        return ['No hay recomendación calculada sobre la cual dictaminar.']
    return []


def _opinion_form(ctx):
    ev = current_ev(ctx)
    opts = [{'value': o['id'], 'label': f"{o['name']} · {o['totals']['commercial']} {o['totals']['currency']}"} for o in (ev.result['offers'] if ev else []) if o['status'] == 'admissible']
    return [F.field('offer_id', 'Oferta recomendada', 'select', options=opts, default=ev.recommended_offer_id if ev else None),
            F.field('reference', 'Referencia del dictamen'), F.field('reason', 'Fundamento del dictamen', 'textarea', rows=4),
            F.field('document_id', 'Dictamen (documento)', 'document', required=False)]


@action('opinion.register', 'Registrar dictamen', 'opinion.register', {'decision'}, form=_opinion_form, blockers=_opinion_blockers,
        done=lambda ctx: bool(db.session.scalar(db.select(Opinion.id).where(Opinion.case_id == ctx.case.id, Opinion.status == 'active'))),
        description='El dictamen recomienda y fundamenta. El ordenador conserva la competencia de adjudicar.')
def opinion_register(ctx, data):
    ev = current_ev(ctx)
    offers = _offers_in_eval(ev)
    offer_id = inp.integer(data, 'offer_id', 'Oferta', minimum=1)
    require(offer_id in offers and offers[offer_id]['status'] == 'admissible', 'validation', 'Solo puede recomendarse una oferta admisible.', 422, {'offer_id': 'Oferta no admisible.'})
    grounds = inp.text(data, 'reason', 'Fundamento', 10, 4000)
    if offer_id != ev.recommended_offer_id:
        require(len(grounds) >= 30, 'validation', 'Una recomendación distinta del cálculo requiere fundamento expreso (30+ caracteres).', 422, {'reason': 'Fundá el apartamiento.'})
    doc = doc_in_case(ctx, data.get('document_id'))
    for old in db.session.scalars(db.select(Opinion).where(Opinion.case_id == ctx.case.id, Opinion.status == 'active')):
        old.status = 'outdated'
    a = ctx.assignment('opinion.register')
    op = Opinion(case_id=ctx.case.id, evaluation_id=ev.id, recommended_offer_id=offer_id, reference=inp.text(data, 'reference', 'Referencia', 2, 200), grounds=grounds,
                 document_id=doc.id if doc else None, author_id=ctx.user.id, assignment_id=a.id if a else None)
    db.session.add(op)
    db.session.flush()
    return {'type': 'opinion', 'id': op.id, 'reference': op.reference, 'reason': grounds, 'details': {'evaluation_version': ev.version, 'offer_id': offer_id}}


# ---------------------------------------------------------------- control preventivo

def _control_blockers(ctx):
    out = []
    ev = current_ev(ctx)
    if ev is None:
        return ['La evaluación vigente fue invalidada: recalculala antes del control.']
    if commission_required(ctx.case) and not db.session.scalar(db.select(Opinion.id).where(Opinion.case_id == ctx.case.id, Opinion.status == 'active')):
        out.append('Falta el dictamen de la comisión asesora (preceptiva por monto).')
    if pending_observation(ctx.case.id):
        out.append('Hay una observación sin respuesta: Compras debe aportar el respaldo antes de una nueva intervención.')
    return out


def _control_form(ctx):
    ev = current_ev(ctx)
    opts = [{'value': o['id'], 'label': o['name']} for o in (ev.result['offers'] if ev else []) if o['status'] == 'admissible']
    return [F.field('offer_id', 'Oferta sobre la que interviene', 'select', options=opts, default=ev.recommended_offer_id if ev else None),
            F.field('result', 'Resultado', 'select', options=F.options([('sin_observacion', 'Sin observación'), ('observado', 'Observado: detener el avance')])),
            *F.ref_reason('Fundamento de la intervención')]


@action('control.register', 'Registrar control preventivo del gasto', 'control.register', {'decision'}, form=_control_form, blockers=_control_blockers,
        description='Representa la intervención preventiva; no es una actuación auténtica del Tribunal de Cuentas. Una observación se conserva.')
def control_register(ctx, data):
    ev = current_ev(ctx)
    offer_id = inp.integer(data, 'offer_id', 'Oferta', minimum=1)
    require(offer_id in _offers_in_eval(ev), 'validation', 'La oferta no integra la evaluación vigente.', 422, {'offer_id': 'Inválida.'})
    a = ctx.assignment('control.register')
    iv = Intervention(case_id=ctx.case.id, kind='control_gasto', result=inp.choice(data, 'result', 'Resultado', ('sin_observacion', 'observado')),
                      reference=inp.text(data, 'reference', 'Referencia', 2, 200), reason=inp.text(data, 'reason', 'Fundamento', 5, 4000), evaluation_id=ev.id,
                      offer_id=offer_id, author_id=ctx.user.id, assignment_id=a.id if a else None)
    db.session.add(iv)
    db.session.flush()
    return {'type': 'intervention', 'id': iv.id, 'reference': iv.reference, 'reason': iv.reason, 'details': {'result': iv.result, 'offer_id': offer_id, 'evaluation_version': ev.version}}


@action('control.respond', 'Aportar respaldo a la observación', 'control.respond', {'decision'},
        form=lambda ctx: [*F.ref_reason('Respuesta / respaldo aportado'), F.field('document_id', 'Documento de respaldo', 'document', required=False)],
        blockers=lambda ctx: [] if pending_observation(ctx.case.id) else ['No hay observaciones pendientes de respuesta.'],
        description='La observación original no se borra: se abre una actuación de respuesta y luego se solicita una nueva intervención.')
def control_respond(ctx, data):
    obs = pending_observation(ctx.case.id)
    doc = doc_in_case(ctx, data.get('document_id'))
    resp = ObservationResponse(intervention_id=obs.id, reference=inp.text(data, 'reference', 'Referencia', 2, 200), reason=inp.text(data, 'reason', 'Respuesta', 5, 4000),
                               document_id=doc.id if doc else None, author_id=ctx.user.id)
    db.session.add(resp)
    db.session.flush()
    return {'type': 'observation_response', 'id': resp.id, 'reference': resp.reference, 'reason': resp.reason, 'details': {'intervention_id': obs.id}}


# ---------------------------------------------------------------- adjudicación

def _award_blockers(ctx):
    out = []
    ev = current_ev(ctx)
    if ev is None:
        return ['La evaluación vigente fue invalidada: recalculala y renová dictamen y control.']
    if ev.result['status'] != 'recommended':
        out.append('La evaluación no tiene recomendación.')
    if commission_required(ctx.case) and not db.session.scalar(db.select(Opinion.id).where(Opinion.case_id == ctx.case.id, Opinion.status == 'active', Opinion.evaluation_id == ev.id)):
        out.append('Falta el dictamen de la comisión sobre la evaluación vigente.')
    if pending_observation(ctx.case.id):
        out.append('La observación del control no tiene respuesta.')
    if not db.session.scalar(db.select(Intervention.id).where(Intervention.case_id == ctx.case.id, Intervention.kind == 'control_gasto', Intervention.status == 'active',
                                                              Intervention.result == 'sin_observacion', Intervention.evaluation_id == ev.id)):
        out.append('Falta un control preventivo sin observación sobre la evaluación vigente.')
    return out


def _award_form(ctx):
    ev = current_ev(ctx)
    opts = [{'value': o['id'], 'label': f"{o['name']} · {o['totals']['commercial']} {o['totals']['currency']}"} for o in (ev.result['offers'] if ev else []) if o['status'] == 'admissible']
    return [F.field('offer_id', 'Oferta que se adjudica', 'select', options=opts, default=ev.recommended_offer_id if ev else None),
            *F.ref_reason('Fundamento de la adjudicación', 'Número de resolución / acto'),
            F.field('departure_reason', 'Motivo de apartamiento (si elegís una oferta distinta de la recomendada)', 'textarea', required=False, rows=3),
            F.field('rupe_exception_reason', 'Excepción reglada a RUPE activo (si corresponde)', 'textarea', required=False, rows=2),
            F.field('vista_reference', 'Constancia de vista previa (art. 67, si corresponde)', required=False),
            F.field('verified', 'Verifiqué RUPE, impedimentos, garantías y demás requisitos aplicables', 'checkbox')]


def _supplier_checks(supplier_id, vista_required, data):
    today = date.today()
    rows = db.session.scalars(db.select(SupplierStatus).where(SupplierStatus.supplier_id == supplier_id).order_by(SupplierStatus.id)).all()

    def current(kind):
        latest = None
        for r in rows:
            if r.kind == kind and (r.valid_from is None or r.valid_from <= today) and (r.valid_to is None or r.valid_to >= today):
                latest = r
        return latest
    imp = current('impedimento')
    require(not (imp and imp.state in ('impedido', 'sancionado')), 'supplier_impediment', 'El proveedor tiene un impedimento vigente registrado: no puede adjudicarse.', 409)
    rupe = current('rupe')
    if not (rupe and rupe.state == 'activo'):
        exc = inp.text(data, 'rupe_exception_reason', 'Excepción RUPE', 20, 1000, required=False)
        require(exc, 'rupe_required', 'El adjudicatario debe tener RUPE activo (registrá la constancia con vigencia) o documentar una excepción reglada.', 409)
    if vista_required:
        require(inp.text(data, 'vista_reference', 'Vista previa', 3, 200, required=False), 'vista_pending',
                'Corresponde la vista previa del art. 67 (más de $ 54.820.000): registrá su constancia antes de adjudicar. No está automatizada.', 409)


@action('award.register', 'Registrar la adjudicación', 'award.register', {'decision'}, form=_award_form, blockers=_award_blockers, competence=True,
        done=lambda ctx: bool(db.session.scalar(db.select(Award.id).where(Award.case_id == ctx.case.id, Award.status == 'active'))),
        description='Vincula autoridad y alcance de competencia, oferta, versión evaluada, monto, dictamen, controles y fundamento.')
def award_register(ctx, data):
    ev = current_ev(ctx)
    offers = _offers_in_eval(ev)
    offer_id = inp.integer(data, 'offer_id', 'Oferta', minimum=1)
    require(offer_id in offers and offers[offer_id]['status'] == 'admissible', 'validation', 'Solo puede adjudicarse una oferta admisible.', 422, {'offer_id': 'No admisible.'})
    require(inp.boolean(data, 'verified'), 'validation', 'Confirmá que verificaste los requisitos aplicables antes de adjudicar.', 422, {'verified': 'Obligatorio.'})
    row = offers[offer_id]
    offer = db.session.get(Offer, offer_id)
    amount, comparable = Decimal(row['totals']['awardable']), Decimal(row['totals']['comparable'])
    assignment = ctx.require_competence(comparable, 'award.register')
    ctrl = db.session.scalar(db.select(Intervention).where(Intervention.case_id == ctx.case.id, Intervention.kind == 'control_gasto', Intervention.status == 'active',
                                                           Intervention.result == 'sin_observacion', Intervention.evaluation_id == ev.id, Intervention.offer_id == offer_id)
                             .order_by(Intervention.id.desc()))
    require(ctrl is not None, 'control_missing', 'Falta un control preventivo sin observación sobre ESTA oferta. Si te apartás de la recomendación, el control debe revisar la oferta elegida.', 409)
    departure = inp.text(data, 'departure_reason', 'Motivo de apartamiento', 30, 4000, required=offer_id != ev.recommended_offer_id)
    opinion = db.session.scalar(db.select(Opinion).where(Opinion.case_id == ctx.case.id, Opinion.status == 'active', Opinion.evaluation_id == ev.id).order_by(Opinion.id.desc()))
    if opinion and opinion.recommended_offer_id != offer_id and not departure:
        raise ApiError('validation', 'Te apartás del dictamen: fundá expresamente el apartamiento.', 422, {'departure_reason': 'Obligatorio.'})
    av = db.session.scalar(db.select(Availability).where(Availability.case_id == ctx.case.id, Availability.status == 'active'))
    require(av is not None and comparable <= av.amount, 'insufficient_credit', 'El monto adjudicado supera la disponibilidad respaldada.', 409)
    vista = bool(ctx.case.currency == 'UYU' and suggest_procedure(ctx.case.estimated_total)['flags']['vista_previa'])
    _supplier_checks(offer.supplier_id, vista, data)
    dv = db.session.scalar(db.select(OfferDataVersion).where(OfferDataVersion.offer_id == offer.id, OfferDataVersion.version == offer.data_version))
    award = Award(case_id=ctx.case.id, evaluation_id=ev.id, offer_id=offer.id, offer_data_version=offer.data_version, amount=amount, currency=row['totals']['currency'],
                  opinion_id=opinion.id if opinion else None, control_id=ctrl.id, reference=inp.text(data, 'reference', 'Resolución', 2, 200),
                  grounds=inp.text(data, 'reason', 'Fundamento', 10, 4000), departure_reason=departure, assignment_id=assignment.id,
                  authority_snapshot={'user_id': ctx.user.id, 'name': ctx.user.full_name, 'role': assignment.role_code, 'assignment_id': assignment.id,
                                      'max_amount': dstr(assignment.max_amount) if assignment.max_amount is not None else None,
                                      'procedures': assignment.procedures, 'legal_basis': assignment.legal_basis},
                  awarded_by=ctx.user.id)
    db.session.add(award)
    db.session.flush()
    by_line = {l['line_id']: l for l in row['totals']['lines']}
    for line in ctx.lines:
        t = by_line[line.id]
        db.session.add(AwardLine(award_id=award.id, request_line_id=line.id, quantity=Decimal(t['quantity']), unit_price=Decimal(t['unit_price']),
                                 tax_rate=next(l.tax_rate for l in dv.lines if l.request_line_id == line.id), amount=Decimal(t['total'])))
    db.session.flush()
    return {'status': 'awarded', 'type': 'award', 'id': award.id, 'reference': award.reference, 'reason': award.grounds,
            'details': {'offer_id': offer.id, 'amount': dstr(amount), 'evaluation_version': ev.version, 'opinion_id': opinion.id if opinion else None,
                        'control_id': ctrl.id, 'departure': bool(departure)}}
