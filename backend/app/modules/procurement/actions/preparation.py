"""Etapa 2 (Preparación): disponibilidad, pliego versionado, autorización del llamado, publicidad y convenio marco."""
from datetime import timedelta
from decimal import Decimal
from app.extensions import db
from app.infrastructure.models import (Availability, BudgetLine, SpecVersion, CaseAuthorization, PublicityRecord, Envelope, Offer, OfferDataVersion,
                                       OfferLine, Supplier, DeadlineExtension)
from app.modules.evaluation.service import mark_dependents_stale
from app.modules.procurement import forms as F, inputs as inp
from app.modules.procurement.actions.common import doc_in_case, effective_deadline, current_round
from app.modules.procurement.framework import action
from app.modules.procurement.service import parse_spec, apply_spec, spec_hash, supplier_by_id, ATTRIBUTES
from app.modules.rules.service import notice_check, PROCEDURE_LABELS
from app.shared.contracts import utcnow, dstr, to_local, display2
from app.shared.errors import ApiError, require


# ---------------------------------------------------------------- disponibilidad

def active_availability(case_id):
    return db.session.scalar(db.select(Availability).where(Availability.case_id == case_id, Availability.status == 'active'))


def _availability_form(ctx):
    lines = db.session.scalars(db.select(BudgetLine).order_by(BudgetLine.fiscal_year.desc(), BudgetLine.item)).all()
    opts = [{'value': b.id, 'label': f'{b.fiscal_year} · {b.item} · {b.funding_source} (libre {display2(b.total_amount - b.committed_amount)})'} for b in lines]
    return [
        F.field('budget_line_id', 'Crédito registrado', 'select', required=False, options=opts, help='Elegí un crédito existente o registrá uno nuevo debajo.'),
        F.field('fiscal_year', 'Ejercicio (si es crédito nuevo)', 'number', required=False),
        F.field('item', 'Rubro / objeto del gasto (si es nuevo)', required=False),
        F.field('funding_source', 'Fuente de financiamiento (si es nuevo)', required=False),
        F.field('total_amount', 'Importe total del crédito (si es nuevo)', 'money', required=False, help='Importe respaldado por documento; no se consulta el sistema financiero.'),
        F.field('credit_support_ref', 'Respaldo del crédito (si es nuevo)', required=False),
        F.field('amount', 'Importe que se imputa a esta compra', 'money', default=dstr(ctx.case.estimated_total), help='La estimación de la solicitud no es crédito disponible.'),
        F.field('availability_date', 'Fecha de la constancia', 'date'),
        F.field('support_ref', 'Respaldo de la disponibilidad (documento/constancia)'),
        F.field('support_document_id', 'Documento de respaldo', 'document', required=False),
    ]


@action('availability.register', 'Respaldar disponibilidad', 'availability.register', {'preparation'}, form=_availability_form,
        blockers=lambda ctx: ['Ya hay una disponibilidad activa; revocala para registrar otra.'] if active_availability(ctx.case.id) else [],
        done=lambda ctx: active_availability(ctx.case.id) is not None,
        description='Contaduría documenta importe, ejercicio, rubro, fuente, fecha y respaldo del crédito.')
def availability_register(ctx, data):
    amount = inp.decimal(data, 'amount', 'Importe a imputar', places=2)
    bl_id = data.get('budget_line_id')
    if bl_id in (None, ''):
        require(ctx.assignment('budget.manage'), 'forbidden', 'No podés registrar créditos nuevos.', 403)
        year = inp.integer(data, 'fiscal_year', 'Ejercicio', minimum=2000, maximum=2100)
        item, source = inp.text(data, 'item', 'Rubro', 2, 60), inp.text(data, 'funding_source', 'Fuente', 2, 80)
        existing = db.session.scalar(db.select(BudgetLine).where(BudgetLine.fiscal_year == year, BudgetLine.item == item, BudgetLine.funding_source == source).with_for_update())
        if existing:
            bl = existing
        else:
            bl = BudgetLine(fiscal_year=year, item=item, funding_source=source, total_amount=inp.decimal(data, 'total_amount', 'Importe del crédito', places=2),
                            committed_amount=Decimal(0), support_ref=inp.text(data, 'credit_support_ref', 'Respaldo del crédito', 3, 200), registered_by=ctx.user.id)
            db.session.add(bl)
            db.session.flush()
    else:
        bl = db.session.scalar(db.select(BudgetLine).where(BudgetLine.id == inp.integer(data, 'budget_line_id', 'Crédito', minimum=1)).with_for_update())
        require(bl is not None, 'validation', 'Crédito inexistente.', 422, {'budget_line_id': 'Inexistente.'})
    free = bl.total_amount - bl.committed_amount
    require(amount <= free, 'insufficient_credit', f'El crédito no alcanza: libre {display2(free)}, solicitado {display2(amount)}.', 409)
    doc = doc_in_case(ctx, data.get('support_document_id'))
    av = Availability(case_id=ctx.case.id, budget_line_id=bl.id, amount=amount, fiscal_year=bl.fiscal_year, budget_item=bl.item, funding_source=bl.funding_source,
                      availability_date=inp.day(data, 'availability_date', 'Fecha de la constancia'), support_ref=inp.text(data, 'support_ref', 'Respaldo', 3, 200),
                      support_document_id=doc.id if doc else None, registered_by=ctx.user.id)
    bl.committed_amount = bl.committed_amount + amount
    db.session.add(av)
    db.session.flush()
    return {'type': 'availability', 'id': av.id, 'reference': av.support_ref, 'reason': f'Disponibilidad de {display2(amount)} ({bl.item}, {bl.fiscal_year}).',
            'details': {'amount': dstr(amount), 'budget_line_id': bl.id, 'covers_estimate': amount >= ctx.case.estimated_total}}


@action('availability.revoke', 'Revocar disponibilidad', 'availability.register', {'preparation'}, danger=True,
        form=lambda ctx: F.ref_reason('Motivo de la revocación'),
        blockers=lambda ctx: [] if active_availability(ctx.case.id) else ['No hay una disponibilidad activa.'],
        description='Libera el crédito imputado. La disponibilidad revocada queda en el historial.')
def availability_revoke(ctx, data):
    av = active_availability(ctx.case.id)
    bl = db.session.scalar(db.select(BudgetLine).where(BudgetLine.id == av.budget_line_id).with_for_update())
    require(not db.session.scalar(db.select(CaseAuthorization.id).where(CaseAuthorization.case_id == ctx.case.id, CaseAuthorization.status == 'active')),
            'blocked', 'El llamado ya fue autorizado con esta disponibilidad.', 409)
    bl.committed_amount = bl.committed_amount - av.amount
    av.status, av.active_key, av.revoked_at = 'revoked', None, utcnow()
    return {'type': 'availability', 'id': av.id, 'reference': inp.text(data, 'reference', 'Referencia', 2, 200), 'reason': inp.text(data, 'reason', 'Motivo', 5, 1000)}


# ---------------------------------------------------------------- pliego

def _spec_form(ctx):
    return [F.field('spec', 'Pliego', 'spec', default=_spec_defaults(ctx))]


def _spec_defaults(ctx):
    from app.modules.procurement.service import spec_content
    s = ctx.spec
    return {**spec_content(s), 'status': s.status, 'version': s.version} if s else None


def _spec_save_blockers(ctx):
    if db.session.scalar(db.select(CaseAuthorization.id).where(CaseAuthorization.case_id == ctx.case.id, CaseAuthorization.spec_version_id == (ctx.spec.id if ctx.spec else 0),
                                                              CaseAuthorization.status == 'active')) and ctx.case.status == 'preparation':
        return []  # una nueva versión es válida: requerirá nueva aprobación y autorización
    return []


@action('spec.save', 'Editar pliego', 'spec.manage', {'preparation', 'receiving_offers'}, form=_spec_form, blockers=_spec_save_blockers,
        description='Requisitos, criterios, escalas y canal. Un pliego aprobado es inmutable: editarlo crea una nueva versión.')
def spec_save(ctx, data):
    case, current = ctx.case, ctx.spec
    content = parse_spec({'spec': data.get('spec', data)}, case.currency)
    if case.procedure_type == 'convenio_marco':
        content['mode'], content['criteria'] = 'framework', []
    reason = inp.text(data, 'change_reason', 'Motivo del cambio', 10, 500, required=current.status == 'approved', default=None)
    if current.status == 'approved':
        new = SpecVersion(case_id=case.id, version=current.version + 1, status='draft', created_by=ctx.user.id, mode=content['mode'], minimum_text='x',
                          similarity_margin=Decimal('0.05'), change_reason=reason)
        db.session.add(new)
        db.session.flush()
        apply_spec(new, content)
        ctx._cache.pop('spec', None)
        return {'type': 'spec', 'id': new.id, 'reason': f'Nueva versión {new.version} del pliego (la {current.version} permanece vigente hasta aprobar la nueva). {reason}',
                'details': {'version': new.version, 'previous': current.version}}
    apply_spec(current, content)
    return {'type': 'spec', 'id': current.id, 'reason': f'Borrador del pliego (versión {current.version}) actualizado.', 'details': {'version': current.version}}


def _spec_approve_blockers(ctx):
    s = ctx.spec
    out = []
    if s is None or s.status != 'draft':
        return ['No hay un borrador de pliego para aprobar.']
    if not s.requirements:
        out.append('El pliego necesita al menos un requisito.')
    if ctx.case.procedure_type is None:
        out.append('Primero se debe encuadrar el procedimiento.')
    if s.mode == 'weighted' and not s.criteria:
        out.append('El modo ponderado requiere criterios con pesos y escalas.')
    competitive = ctx.case.procedure_type not in (None, 'convenio_marco')
    if competitive and (s.offer_deadline is None or not s.reception_channel):
        out.append('Fijá el plazo y el canal de recepción de ofertas.')
    if s.offer_deadline and s.offer_deadline <= utcnow() and ctx.case.status == 'preparation':
        out.append('El plazo de recepción debe ser posterior al momento actual.')
    return out


@action('spec.approve', 'Aprobar pliego', 'spec.manage', {'preparation', 'receiving_offers'}, blockers=_spec_approve_blockers,
        form=lambda ctx: [F.field('communicated_ref', 'Referencia de comunicación a todos los interesados', required=ctx.case.status == 'receiving_offers',
                                  help='Obligatoria si el cambio se produce con el llamado en curso: no pueden existir condiciones distintas por oferente.'),
                          F.field('reason', 'Constancia', 'textarea', rows=2, required=False)],
        done=lambda ctx: ctx.spec is not None and ctx.spec.status == 'approved',
        description='Fija las reglas. Después de aprobado no se reescribe: los cambios generan nueva versión.')
def spec_approve(ctx, data):
    s = ctx.spec
    if ctx.case.status == 'receiving_offers':
        inp.text(data, 'communicated_ref', 'Comunicación a interesados', 3, 200)
    s.content_hash = spec_hash(s)
    for old in db.session.scalars(db.select(SpecVersion).where(SpecVersion.case_id == ctx.case.id, SpecVersion.status == 'approved')):
        old.status = 'superseded'
    s.status, s.approved_by, s.approved_at = 'approved', ctx.user.id, utcnow()
    if ctx.case.status == 'receiving_offers':
        mark_dependents_stale(ctx.case, f'Nueva versión del pliego ({s.version}).')
    return {'type': 'spec', 'id': s.id, 'reference': f'PL-{ctx.case.code}-v{s.version}', 'reason': f'Pliego versión {s.version} aprobado y fijado.',
            'details': {'version': s.version, 'content_hash': s.content_hash}}


# ---------------------------------------------------------------- autorización del llamado

def _call_blockers(ctx):
    out = []
    av = active_availability(ctx.case.id)
    if av is None:
        out.append('Falta la disponibilidad respaldada por Contaduría.')
    elif av.amount < ctx.case.estimated_total:
        out.append(f'La disponibilidad ({display2(av.amount)}) no cubre la estimación ({display2(ctx.case.estimated_total)}).')
    s = ctx.spec
    if s is None or s.status != 'approved':
        out.append('El pliego debe estar aprobado.')
    if ctx.case.procedure_type is None:
        out.append('Falta encuadrar el procedimiento.')
    return out


def _call_authorized(ctx):
    return bool(ctx.spec and db.session.scalar(db.select(CaseAuthorization.id).where(
        CaseAuthorization.case_id == ctx.case.id, CaseAuthorization.spec_version_id == ctx.spec.id, CaseAuthorization.status == 'active')))


@action('call.authorize', 'Autorizar el llamado', 'call.authorize', {'preparation'}, blockers=_call_blockers, done=_call_authorized, competence=True,
        form=lambda ctx: F.ref_reason('Fundamento de la autorización'),
        description='El ordenador competente autoriza procedimiento y condiciones. La cuenta de administrador técnico no tiene esta competencia.')
def call_authorize(ctx, data):
    require(not _call_authorized(ctx), 'conflict', 'Este pliego ya tiene una autorización vigente.', 409)
    a = ctx.require_competence(ctx.case.estimated_total, 'call.authorize')
    auth = CaseAuthorization(case_id=ctx.case.id, kind='call', spec_version_id=ctx.spec.id, reference=inp.text(data, 'reference', 'Referencia', 2, 200),
                             grounds=inp.text(data, 'reason', 'Fundamento', 10, 2000), assignment_id=a.id, authorized_by=ctx.user.id)
    db.session.add(auth)
    db.session.flush()
    return {'type': 'authorization', 'id': auth.id, 'reference': auth.reference, 'reason': auth.grounds,
            'details': {'spec_version': ctx.spec.version, 'procedure_type': ctx.case.procedure_type}}


# ---------------------------------------------------------------- publicidad

def _publicity_form(ctx):
    return [
        F.field('kind', 'Tipo de actuación', 'select', options=F.options([('convocatoria', 'Convocatoria publicada'), ('invitacion', 'Invitación a proveedores')])),
        F.field('state', 'Estado', 'select', options=F.options([('pending', 'Pendiente: aún no publicada'), ('external_constancia', 'Constancia de publicación externa (ARCE/sitio)')]),
                help='“Publicación confirmada por integración” no está disponible: no hay integración conectada.'),
        F.field('reference', 'Referencia de la publicación o invitación', required=False, help='Obligatoria cuando hay constancia externa.'),
        F.field('published_on', 'Fecha de publicación', 'date', required=False),
        F.field('document_id', 'Constancia (documento)', 'document', required=False),
        F.field('notice_justification', 'Justificación de antelación reducida', 'textarea', required=False, rows=2,
                help='Solo si la antelación es menor a la de referencia; requiere verificación jurídica.'),
    ]


def _publicity_blockers(ctx):
    out = []
    if ctx.case.procedure_type == 'convenio_marco':
        out.append('El convenio marco no se publica: se registra la selección autorizada.')
    if not _call_authorized(ctx):
        out.append('Falta la autorización del llamado para la versión vigente del pliego.')
    return out


@action('publicity.register', 'Registrar publicidad y abrir recepción', 'publicity.register', {'preparation'}, form=_publicity_form, blockers=_publicity_blockers,
        description='Distingue publicación pendiente de constancia externa. Una constancia interna no prueba que la publicación haya ocurrido.')
def publicity_register(ctx, data):
    state = inp.choice(data, 'state', 'Estado', ('pending', 'external_constancia'))
    ref = inp.text(data, 'reference', 'Referencia', 3, 200, required=state == 'external_constancia')
    published = inp.day(data, 'published_on', 'Fecha de publicación', required=state == 'external_constancia')
    doc = doc_in_case(ctx, data.get('document_id'))
    note = None
    spec = ctx.spec
    if state == 'external_constancia' and spec.offer_deadline:
        check = notice_check(ctx.case.procedure_type, published, to_local(spec.offer_deadline).date(), False, data.get('notice_justification'))
        if check['applies'] and not check['ok']:
            raise ApiError('notice_short', check['warnings'][0], 422, {'notice_justification': 'Justificá la antelación reducida.'}, extra={'warnings': check['warnings']})
        note = ' '.join(check['warnings']) or None
    rec = PublicityRecord(case_id=ctx.case.id, spec_version_id=spec.id, kind=inp.choice(data, 'kind', 'Tipo', ('convocatoria', 'invitacion')), state=state,
                          reference=ref, published_at=utcnow() if state != 'pending' else None, document_id=doc.id if doc else None,
                          notice_note=note, created_by=ctx.user.id)
    db.session.add(rec)
    db.session.flush()
    result = {'type': 'publicity', 'id': rec.id, 'reference': ref, 'reason': f'Publicidad: {state}.', 'details': {'state': state, 'kind': rec.kind, 'warning': note}}
    if state != 'pending':
        result['status'] = 'receiving_offers'
        result['reason'] = 'Constancia de publicación externa registrada; se abre la recepción de ofertas.'
    return result


# ---------------------------------------------------------------- convenio marco

def _framework_form(ctx):
    return [
        F.field('agreement_ref', 'Convenio marco / instrumento vigente'),
        F.field('supplier_id', 'Proveedor seleccionado', 'select', options=_supplier_opts()),
        F.field('evidence_note', 'Constancia de la selección autorizada', 'textarea', rows=3),
        F.field('lines', 'Precios de la selección', 'lines', fields=[
            F.field('request_line_id', 'Renglón', 'select', options=[{'value': l.id, 'label': f'{l.position}. {l.description}'} for l in ctx.lines]),
            F.field('unit_price', 'Precio unitario', 'money'), F.field('tax_rate', 'IVA (%)', 'number')]),
        F.field('delivery_days', 'Plazo de entrega (días)', 'number', required=False), F.field('warranty_months', 'Garantía (meses)', 'number', required=False),
    ]


def _supplier_opts():
    return [{'value': s.id, 'label': s.name} for s in db.session.scalars(db.select(Supplier).where(Supplier.active.is_(True)).order_by(Supplier.name))]


def _framework_blockers(ctx):
    out = []
    if ctx.case.procedure_type != 'convenio_marco':
        out.append('Esta compra no está encuadrada como convenio marco.')
    if not _call_authorized(ctx):
        out.append('Falta la autorización del procedimiento.')
    return out


@action('framework.select', 'Registrar selección en convenio marco', 'framework.select', {'preparation'}, form=_framework_form, blockers=_framework_blockers,
        description='No se realiza un nuevo llamado: se registra la selección del instrumento vigente con su constancia.')
def framework_select(ctx, data):
    from app.modules.procurement.actions.offers import write_offer_data
    supplier = supplier_by_id(inp.integer(data, 'supplier_id', 'Proveedor', minimum=1))
    ref = inp.text(data, 'agreement_ref', 'Convenio', 3, 200)
    env = Envelope(case_id=ctx.case.id, spec_version_id=ctx.spec.id, supplier_id=supplier.id, receipt_code=f'{ctx.case.code}-CM', channel='convenio_marco',
                   deadline_at=utcnow(), on_time=True, custody_note=inp.text(data, 'evidence_note', 'Constancia', 5, 300), status='received',
                   opened_at=utcnow(), created_by=ctx.user.id, round=current_round(ctx.case))
    db.session.add(env)
    db.session.flush()
    offer = Offer(case_id=ctx.case.id, envelope_id=env.id, supplier_id=supplier.id, currency=ctx.case.currency)
    db.session.add(offer)
    db.session.flush()
    write_offer_data(ctx, offer, data, reason=f'Selección en {ref}')
    return {'status': 'offers_opened', 'type': 'offer', 'id': offer.id, 'reference': ref, 'reason': f'Selección en convenio marco: {supplier.name}.',
            'details': {'supplier_id': supplier.id}}
