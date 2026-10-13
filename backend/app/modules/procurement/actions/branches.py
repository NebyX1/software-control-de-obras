"""Ramas jurídicas que no se resuelven con un botón: cancelación, desierto, rechazo de ofertas, excepción y reinicio."""
from decimal import Decimal
from app.extensions import db
from app.infrastructure.models import BranchRecord, Envelope, SpecVersion, Award
from app.modules.evaluation import service as evals
from app.modules.procurement import forms as F, inputs as inp
from app.modules.procurement.actions.common import doc_in_case, current_round, effective_deadline
from app.modules.procurement.framework import action
from app.modules.procurement.service import apply_spec, spec_content
from app.shared.contracts import utcnow
from app.shared.errors import require

PRE_AWARD = {'preparation', 'receiving_offers', 'offers_opened', 'evaluation', 'decision'}


def _branch(ctx, kind, data, extra=None, reason_len=10):
    rec = BranchRecord(case_id=ctx.case.id, kind=kind, reason=inp.text(data, 'reason', 'Motivo', reason_len, 4000), reference=inp.text(data, 'reference', 'Referencia', 2, 200, required=False),
                       detail=extra or {}, created_by=ctx.user.id)
    db.session.add(rec)
    db.session.flush()
    ctx.case.branch = {'kind': kind, 'record_id': rec.id, 'at': utcnow().isoformat()}
    return rec


@action('case.cancel', 'Cancelar el procedimiento', 'case.cancel', PRE_AWARD | {'submitted'}, danger=True,
        form=lambda ctx: F.ref_reason('Motivo de la cancelación (desistimiento motivado)'),
        blockers=lambda ctx: ['Una compra adjudicada requiere otra actuación jurídica, no una cancelación simple.'] if db.session.scalar(db.select(Award.id).where(Award.case_id == ctx.case.id, Award.status == 'active')) else [],
        description='Registra un desistimiento motivado. No se confunde con un llamado desierto y conserva todo el expediente.')
def case_cancel(ctx, data):
    rec = _branch(ctx, 'cancelled', data)
    return {'status': 'cancelled', 'type': 'branch', 'id': rec.id, 'reference': rec.reference, 'reason': rec.reason}


def _desert_blockers(ctx):
    if ctx.case.status == 'receiving_offers':
        d = effective_deadline(ctx.case, ctx.spec)
        n = db.session.scalar(db.select(db.func.count(Envelope.id)).where(Envelope.case_id == ctx.case.id, Envelope.round == current_round(ctx.case), Envelope.status == 'received'))
        if d and utcnow() < d:
            return ['El plazo de recepción aún no venció.']
        if n:
            return ['Hay sobres recibidos en plazo: corresponde realizar la apertura.']
        return []
    ev = evals.current_evaluation(ctx.case.id)
    if not evals.evaluable_offers(ctx.case):
        return []
    return ['Hay ofertas evaluables: si ninguna es admisible, usá “rechazar todas las ofertas”.']


@action('branch.deserted', 'Declarar desierto', 'branch.deserted', {'receiving_offers', 'offers_opened', 'evaluation'}, form=lambda ctx: F.ref_reason('Motivo (ausencia de ofertas)'), blockers=_desert_blockers,
        description='Un procedimiento desierto abre ramas jurídicas específicas (nueva convocatoria o excepción), no un simple cambio de estado.')
def branch_deserted(ctx, data):
    rec = _branch(ctx, 'deserted', data)
    return {'status': 'deserted', 'type': 'branch', 'id': rec.id, 'reference': rec.reference, 'reason': rec.reason}


def _reject_blockers(ctx):
    ev = evals.current_evaluation(ctx.case.id)
    if ev is None:
        return ['Calculá la evaluación vigente antes de rechazar las ofertas.']
    return []


@action('offers.reject_all', 'Rechazar todas las ofertas', 'branch.reject_offers', {'offers_opened', 'evaluation', 'decision'}, blockers=_reject_blockers,
        form=lambda ctx: [F.field('cause', 'Causa', 'select', options=F.options([('inadmisibles', 'Todas inadmisibles'), ('inconvenientes', 'Inconvenientes (fundamento expreso)')])), *F.ref_reason('Fundamento')],
        description='Ofertas inadmisibles e inconvenientes son situaciones distintas con consecuencias distintas.')
def offers_reject_all(ctx, data):
    cause = inp.choice(data, 'cause', 'Causa', ('inadmisibles', 'inconvenientes'))
    ev = evals.current_evaluation(ctx.case.id)
    if cause == 'inadmisibles':
        require(not any(o['status'] in ('admissible', 'pending') for o in ev.result['offers']), 'blocked', 'Hay ofertas admisibles o pendientes de verificar: no corresponde declararlas inadmisibles.', 409)
    else:
        require(len(inp.text(data, 'reason', 'Fundamento', 30, 4000)) >= 30, 'validation', 'El fundamento debe ser expreso.', 422, {'reason': 'Fundamento insuficiente.'})
    rec = _branch(ctx, 'offers_rejected', data, {'cause': cause, 'evaluation_version': ev.version})
    return {'status': 'offers_rejected', 'type': 'branch', 'id': rec.id, 'reference': rec.reference, 'reason': rec.reason}


@action('exception.request', 'Tramitar revisión de excepción', 'branch.exception', {'deserted', 'offers_rejected'},
        form=lambda ctx: [F.field('cause', 'Causal invocada'), F.field('facts', 'Hechos que la justifican', 'textarea', rows=4), F.field('document_id', 'Documentación respaldatoria', 'document', required=False),
                          *F.ref_reason('Fundamento')],
        description='No se habilita porque alguien marque “urgente”: se abre una revisión documental competente, sin recomendación automática.')
def exception_request(ctx, data):
    doc = doc_in_case(ctx, data.get('document_id'))
    rec = _branch(ctx, 'exception', data, {'cause': inp.text(data, 'cause', 'Causal', 5, 300), 'facts': inp.text(data, 'facts', 'Hechos', 20, 4000), 'document_id': doc.id if doc else None})
    return {'status': 'exception_review', 'type': 'branch', 'id': rec.id, 'reference': rec.reference, 'reason': rec.reason,
            'details': {'note': 'Sin recomendación automática; requiere revisión documental competente.'}}


@action('exception.resolve', 'Registrar resolución de la excepción', 'branch.exception', {'exception_review'},
        form=lambda ctx: [F.field('outcome', 'Resultado', 'select', options=F.options([('authorized', 'Excepción autorizada por acto externo'), ('rejected', 'Excepción rechazada')])),
                          F.field('document_id', 'Acto auténtico (documento)', 'document', required=False, help='Obligatorio para registrar una excepción autorizada: no basta marcar una casilla.'),
                          *F.ref_reason('Fundamento', 'Referencia del acto / expediente externo')],
        competence=True, description='Un expediente externo no se presenta como resuelto sin el acto auténtico incorporado.')
def exception_resolve(ctx, data):
    outcome = inp.choice(data, 'outcome', 'Resultado', ('authorized', 'rejected'))
    ctx.require_competence(None, 'branch.exception')
    open_rec = db.session.scalar(db.select(BranchRecord).where(BranchRecord.case_id == ctx.case.id, BranchRecord.kind == 'exception', BranchRecord.state == 'open').order_by(BranchRecord.id.desc()))
    if open_rec:
        open_rec.state = 'resolved'
    if outcome == 'authorized':
        doc_in_case(ctx, data.get('document_id'), required=True, label='Acto auténtico')
        ctx.case.procedure_type = 'excepcion'
        rec = _branch(ctx, 'exception_authorized', data)
        return {'status': 'preparation', 'type': 'branch', 'id': rec.id, 'reference': rec.reference, 'reason': rec.reason,
                'details': {'note': 'Se reanuda la preparación; deben renovarse disponibilidad, pliego y autorización según corresponda.'}}
    rec = _branch(ctx, 'exception_rejected', data)
    return {'status': 'cancelled', 'type': 'branch', 'id': rec.id, 'reference': rec.reference, 'reason': rec.reason}


@action('procedure.restart', 'Reiniciar el procedimiento', 'branch.restart', {'deserted', 'offers_rejected', 'exception_review'},
        form=lambda ctx: F.ref_reason('Fundamento del nuevo llamado'),
        description='Abre una nueva ronda: nuevo pliego en borrador, nueva aprobación y autorización. La ronda anterior se conserva.')
def procedure_restart(ctx, data):
    rec = _branch(ctx, 'restart', data)
    flags = dict(ctx.case.flags or {})
    flags['round'] = current_round(ctx.case) + 1
    ctx.case.flags = flags
    last = ctx.spec
    new = SpecVersion(case_id=ctx.case.id, version=(db.session.scalar(db.select(db.func.max(SpecVersion.version)).where(SpecVersion.case_id == ctx.case.id)) or 0) + 1,
                      status='draft', created_by=ctx.user.id, mode=last.mode, minimum_text='x', similarity_margin=Decimal('0.05'), change_reason=inp.text(data, 'reason', 'Motivo', 10, 500))
    db.session.add(new)
    db.session.flush()
    content = spec_content(last)
    content['offer_deadline'] = None
    content['similarity_margin'] = Decimal(content['similarity_margin'])
    content['requirements'] = [{**r, 'position': i, 'unit': None, 'threshold': Decimal(r['threshold']) if r['threshold'] is not None else None} for i, r in enumerate(content['requirements'], 1)]
    content['criteria'] = [{**c, 'position': i, 'description': None, 'weight': Decimal(c['weight'])} for i, c in enumerate(content['criteria'], 1)]
    apply_spec(new, content)
    return {'status': 'preparation', 'type': 'branch', 'id': rec.id, 'reference': rec.reference, 'reason': rec.reason, 'details': {'round': flags['round'], 'spec_version': new.version}}
