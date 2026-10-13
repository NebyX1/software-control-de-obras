"""Etapa 3 (Ofertas) y revisión previa a la evaluación: custodia de sobres, apertura, datos validados y requisitos."""
from decimal import Decimal
from app.extensions import db
from app.infrastructure.models import (Envelope, Offer, OfferDataVersion, OfferLine, DeadlineExtension, OpeningRecord, RequirementReview, ManualScore,
                                       Subsanation, Document, DocumentVersion, Supplier)
from app.infrastructure import tasks
from app.modules.evaluation.service import mark_dependents_stale, latest_reviews
from app.modules.procurement import forms as F, inputs as inp
from app.modules.procurement.actions.common import doc_in_case, offer_in_case, spec_requirement, effective_deadline, current_round, supplier_choices
from app.modules.procurement.framework import action
from app.modules.procurement.service import supplier_by_id
from app.shared.contracts import utcnow, dstr, to_local, iso_utc
from app.shared.errors import require

CHANNELS = {'presencial': 'Recepción presencial', 'electronico_arce': 'Apertura electrónica ARCE (registro de lo recibido)', 'correo_pliego': 'Correo habilitado por el pliego', 'otro': 'Otro canal definido en el pliego'}


# ---------------------------------------------------------------- sobres

def _envelope_form(ctx):
    return [F.field('supplier_id', 'Proveedor', 'select', options=supplier_choices()),
            F.field('channel', 'Canal por el que llegó', 'select', options=F.options(list(CHANNELS.items())),
                    help='Debe ser el canal autorizado por el pliego; los demás no se admiten.'),
            F.field('custody_note', 'Custodia / constancia de recepción', 'textarea', rows=2, help='Quién lo recibió y dónde queda custodiado.')]


def _receiving_blockers(ctx):
    d = effective_deadline(ctx.case, ctx.spec)
    return [] if d else ['El pliego no tiene plazo de recepción.']


@action('envelope.register', 'Registrar sobre recibido', 'envelope.register', {'receiving_offers'}, form=_envelope_form, blockers=_receiving_blockers,
        description='La fecha y hora las fija el servidor (America/Montevideo). El contenido permanece reservado hasta la apertura.')
def envelope_register(ctx, data):
    spec, now = ctx.spec, utcnow()
    channel = inp.choice(data, 'channel', 'Canal', tuple(CHANNELS))
    require(channel == spec.reception_channel, 'channel_not_authorized',
            f'Canal no habilitado: el pliego autoriza “{CHANNELS.get(spec.reception_channel, spec.reception_channel)}”. Un canal no habilitado no registra la oferta.', 422,
            {'channel': 'Canal no habilitado por el pliego.'})
    supplier = supplier_by_id(inp.integer(data, 'supplier_id', 'Proveedor', minimum=1))
    deadline = effective_deadline(ctx.case, spec)
    on_time = now <= deadline
    n = db.session.scalar(db.select(db.func.count(Envelope.id)).where(Envelope.case_id == ctx.case.id)) + 1
    env = Envelope(case_id=ctx.case.id, spec_version_id=spec.id, supplier_id=supplier.id, receipt_code=f'{ctx.case.code}-S{n:02d}', channel=channel,
                   deadline_at=deadline, on_time=on_time, custody_note=inp.text(data, 'custody_note', 'Custodia', 5, 300), status='received' if on_time else 'late',
                   created_by=ctx.user.id, round=current_round(ctx.case))
    db.session.add(env)
    db.session.flush()
    msg = 'Sobre recibido en plazo.' if on_time else 'Sobre recibido FUERA DE PLAZO: queda registrado y no será abierto ni evaluado.'
    return {'type': 'envelope', 'id': env.id, 'reference': env.receipt_code, 'reason': msg,
            'details': {'supplier_id': supplier.id, 'on_time': on_time, 'channel': channel, 'deadline': iso_utc(deadline)}}


@action('deadline.extend', 'Prorrogar el plazo de recepción', 'deadline.extend', {'receiving_offers'},
        form=lambda ctx: [F.field('new_deadline', 'Nuevo plazo (hora de Montevideo)', 'datetime'),
                          F.field('communicated_ref', 'Referencia de la comunicación uniforme a todos los interesados'),
                          F.field('reason', 'Motivo de la prórroga', 'textarea', rows=2)],
        description='La prórroga se comunica a todos por igual y queda registrada; no se otorgan condiciones privadas.')
def deadline_extend(ctx, data):
    current = effective_deadline(ctx.case, ctx.spec)
    new = inp.moment(data, 'new_deadline', 'Nuevo plazo')
    require(current > utcnow(), 'deadline_passed', 'El plazo ya venció: no se puede prorrogar retroactivamente.', 409)
    require(new > current, 'validation', 'El nuevo plazo debe ser posterior al vigente.', 422, {'new_deadline': 'Debe ser posterior al plazo vigente.'})
    ext = DeadlineExtension(case_id=ctx.case.id, previous_deadline=current, new_deadline=new, reason=inp.text(data, 'reason', 'Motivo', 5, 500),
                            communicated_ref=inp.text(data, 'communicated_ref', 'Comunicación', 3, 200), created_by=ctx.user.id)
    db.session.add(ext)
    db.session.flush()
    return {'type': 'deadline_extension', 'id': ext.id, 'reference': ext.communicated_ref, 'reason': ext.reason,
            'details': {'previous': iso_utc(current), 'new': iso_utc(new)}}


def _opening_blockers(ctx):
    deadline = effective_deadline(ctx.case, ctx.spec)
    out = []
    if deadline and utcnow() < deadline:
        out.append(f'La apertura no puede realizarse antes del vencimiento del plazo ({to_local(deadline):%d/%m/%Y %H:%M} hora de Montevideo).')
    n = db.session.scalar(db.select(db.func.count(Envelope.id)).where(Envelope.case_id == ctx.case.id, Envelope.round == current_round(ctx.case), Envelope.status == 'received'))
    if not n:
        out.append('No hay sobres recibidos en plazo. Corresponde que el ordenador declare el procedimiento desierto.')
    return out


@action('opening.perform', 'Realizar el acto de apertura', 'opening.perform', {'receiving_offers'}, blockers=_opening_blockers,
        form=lambda ctx: [F.field('reference', 'Número del acta de apertura'),
                          F.field('participants', 'Participantes del acto', 'textarea', rows=3, help='Una persona por línea, con su función.'),
                          F.field('minutes_document_id', 'Acta (documento)', 'document', required=False),
                          F.field('notes', 'Observaciones del acto', 'textarea', required=False, rows=2)],
        description='Libera el contenido de los sobres recibidos en plazo. La admisibilidad se estudia después, no en el acto.')
def opening_perform(ctx, data):
    now, rnd = utcnow(), current_round(ctx.case)
    envs = db.session.scalars(db.select(Envelope).where(Envelope.case_id == ctx.case.id, Envelope.round == rnd, Envelope.status == 'received').with_for_update()).all()
    participants = [p.strip() for p in inp.text(data, 'participants', 'Participantes', 3, 2000).splitlines() if p.strip()]
    require(participants, 'validation', 'Registrá al menos un participante.', 422, {'participants': 'Obligatorio.'})
    minutes = doc_in_case(ctx, data.get('minutes_document_id'))
    rec = OpeningRecord(case_id=ctx.case.id, opened_at=now, reference=inp.text(data, 'reference', 'Acta', 2, 200), participants=participants,
                        minutes_document_id=minutes.id if minutes else None, envelope_count=len(envs), round=rnd,
                        notes=inp.text(data, 'notes', 'Observaciones', 1, 2000, required=False), created_by=ctx.user.id)
    db.session.add(rec)
    queued = 0
    for env in envs:
        env.opened_at = now
        db.session.add(Offer(case_id=ctx.case.id, envelope_id=env.id, supplier_id=env.supplier_id, currency=ctx.case.currency))
        rows = db.session.execute(db.select(DocumentVersion, Document).join(Document, Document.id == DocumentVersion.document_id)
                                  .where(Document.envelope_id == env.id, Document.status == 'active')).all()
        for ver, doc in rows:
            ver.text_status = 'pending'
            if doc.classification != 'confidential':
                tasks.enqueue('document_ingest', {'document_version_id': ver.id}, case_id=ctx.case.id, user_id=ctx.user.id, dedupe_key=f'ingest:{ver.id}')
                queued += 1
            else:
                ver.text_status = 'held_confidential'
    db.session.flush()
    return {'status': 'offers_opened', 'type': 'opening', 'id': rec.id, 'reference': rec.reference, 'reason': f'Apertura de {len(envs)} sobre(s).',
            'details': {'envelopes': len(envs), 'ingest_tasks': queued}}


# ---------------------------------------------------------------- datos de la oferta

def write_offer_data(ctx, offer, data, reason):
    """Crea una nueva versión de los datos validados de una oferta (nunca modifica una versión previa ni el sobre original)."""
    lines = inp.items(data, 'lines', 'Renglones cotizados', 1, 100)
    req_lines = {l.id: l for l in ctx.lines}
    version = offer.data_version + 1
    dv = OfferDataVersion(offer_id=offer.id, version=version, currency=inp.text(data, 'currency', 'Moneda', 3, 3, required=False, default=ctx.case.currency).upper(),
                          prices_include_tax=inp.boolean(data, 'prices_include_tax'), freight=inp.decimal(data, 'freight', 'Flete', required=False, positive=False, places=2, default=Decimal(0)),
                          freight_includes_tax=inp.boolean(data, 'freight_includes_tax', True),
                          freight_tax_rate=inp.decimal(data, 'freight_tax_rate', 'IVA del flete', required=False, positive=False, maximum=100, default=Decimal(0), places=3),
                          discount_total=inp.decimal(data, 'discount_total', 'Descuento global', required=False, positive=False, places=2, default=Decimal(0)),
                          delivery_days=inp.integer(data, 'delivery_days', 'Plazo de entrega', required=False, minimum=0, maximum=3650),
                          warranty_months=inp.integer(data, 'warranty_months', 'Garantía', required=False, minimum=0, maximum=1200),
                          delivery_terms=inp.text(data, 'delivery_terms', 'Condición de entrega', 2, 60, required=False),
                          evidence=data.get('evidence') if isinstance(data.get('evidence'), dict) else None, reason=reason, recorded_by=ctx.user.id)
    seen = set()
    for i, row in enumerate(lines, 1):
        rl_id = inp.integer(row, 'request_line_id', f'Renglón {i}', minimum=1)
        require(rl_id in req_lines and rl_id not in seen, 'validation', f'Renglón {i}: inválido o repetido.', 422, {'lines': 'Renglón inválido.'})
        seen.add(rl_id)
        dv.lines.append(OfferLine(request_line_id=rl_id, unit_price=inp.decimal(row, 'unit_price', f'Renglón {i}: precio', places=4),
                                  quantity=inp.decimal(row, 'quantity', f'Renglón {i}: cantidad', required=False, places=4),
                                  tax_rate=inp.decimal(row, 'tax_rate', f'Renglón {i}: IVA', positive=False, maximum=100, places=3, required=False, default=Decimal(0)),
                                  discount=inp.decimal(row, 'discount', f'Renglón {i}: descuento', required=False, positive=False, places=2, default=Decimal(0))))
    db.session.add(dv)
    offer.data_version, offer.currency, offer.status = version, dv.currency, 'data_recorded'
    db.session.flush()
    return dv


def _offer_choices(ctx):
    rows = db.session.execute(db.select(Offer, Supplier).join(Supplier, Supplier.id == Offer.supplier_id)
                              .where(Offer.case_id == ctx.case.id).order_by(Offer.id)).all()
    return [{'value': o.id, 'label': s.name} for o, s in rows]


def _record_form(ctx):
    return [F.field('offer_id', 'Oferta', 'select', options=_offer_choices(ctx)),
            F.field('currency', 'Moneda de la oferta', 'text', default=ctx.case.currency),
            F.field('prices_include_tax', 'Los precios incluyen impuestos', 'checkbox', required=False),
            F.field('lines', 'Precios por renglón', 'lines', fields=[
                F.field('request_line_id', 'Renglón', 'select', options=[{'value': l.id, 'label': f'{l.position}. {l.description} ({dstr(l.quantity)} {l.unit})'} for l in ctx.lines]),
                F.field('unit_price', 'Precio unitario', 'money'), F.field('tax_rate', 'IVA (%)', 'number', required=False),
                F.field('discount', 'Descuento', 'money', required=False)]),
            F.field('freight', 'Flete y otros', 'money', required=False), F.field('freight_includes_tax', 'El flete incluye impuestos', 'checkbox', required=False),
            F.field('freight_tax_rate', 'IVA del flete (%)', 'number', required=False), F.field('discount_total', 'Descuento global', 'money', required=False),
            F.field('delivery_days', 'Plazo de entrega (días)', 'number', required=False), F.field('warranty_months', 'Garantía (meses)', 'number', required=False),
            F.field('delivery_terms', 'Condición de entrega (ej. entregado en depósito, CIF)', required=False),
            F.field('reason', 'Fuente del dato / motivo', 'textarea', rows=2, help='Documento y página de donde surge; puede venir de campos extraídos y revisados.')]


def _data_stage_blockers(ctx):
    if not ctx.spec or ctx.spec.status != 'approved':
        return ['No hay un pliego aprobado.']
    return []


@action('offer.record', 'Registrar datos validados de una oferta', 'offer.record', {'offers_opened', 'evaluation', 'decision'}, form=_record_form, blockers=_data_stage_blockers,
        description='Genera una nueva versión de datos; el sobre original nunca se modifica. Invalida evaluaciones y revisiones que dependían del dato anterior.')
def offer_record(ctx, data):
    offer = offer_in_case(ctx, data.get('offer_id'))
    env = db.session.get(Envelope, offer.envelope_id)
    require(env.opened_at is not None and env.status == 'received', 'sealed', 'La oferta no está abierta o fue recibida fuera de plazo.', 409)
    dv = write_offer_data(ctx, offer, data, inp.text(data, 'reason', 'Fuente / motivo', 5, 500))
    stale = mark_dependents_stale(ctx.case, f'Cambió el dato de la oferta {offer.id} (versión {dv.version}).')
    return {'type': 'offer', 'id': offer.id, 'reference': f'v{dv.version}', 'reason': dv.reason, 'details': {'data_version': dv.version, 'evaluations_invalidated': stale}}


# ---------------------------------------------------------------- revisión de requisitos

def _review_form(ctx):
    reqs = [{'value': r.id, 'label': f'{r.code}: {r.text}'} for r in (ctx.spec.requirements if ctx.spec else []) if r.kind == 'review']
    return [F.field('offer_id', 'Oferta', 'select', options=_offer_choices(ctx)), F.field('requirement_id', 'Requisito', 'select', options=reqs),
            F.field('result', 'Conclusión', 'select', options=F.options([('met', 'Cumple'), ('not_met', 'No cumple'), ('pending', 'Pendiente de verificar')]),
                    help='“Pendiente” no es incumplimiento: la ausencia de evidencia no excluye una oferta.'),
            F.field('treatment', 'Tratamiento de la carencia', 'select', required=False, options=F.options([('subsanable', 'Carencia formal subsanable'), ('no_subsanable', 'No subsanable')])),
            F.field('observed_value', 'Dato observado', required=False), F.field('document_id', 'Documento de evidencia', 'document', required=False),
            F.field('page', 'Página', 'number', required=False), F.field('quote', 'Fragmento textual', 'textarea', required=False, rows=2),
            F.field('note', 'Observación del revisor', 'textarea', required=False, rows=2)]


@action('requirement.review', 'Revisar requisito', 'requirement.review', {'offers_opened', 'evaluation', 'decision'}, form=_review_form, blockers=_data_stage_blockers,
        description='Cada conclusión conserva evidencia, revisor y fecha. El juicio técnico queda atribuido a una persona.')
def requirement_review(ctx, data):
    offer = offer_in_case(ctx, data.get('offer_id'))
    req = spec_requirement(ctx.spec, data.get('requirement_id'))
    require(req.kind == 'review', 'validation', 'Ese requisito numérico se verifica automáticamente con los datos de la oferta.', 422, {'requirement_id': 'No revisable.'})
    result = inp.choice(data, 'result', 'Conclusión', ('met', 'not_met', 'pending'))
    treatment = inp.choice(data, 'treatment', 'Tratamiento', ('subsanable', 'no_subsanable'), required=result == 'not_met')
    doc = doc_in_case(ctx, data.get('document_id'))
    note = inp.text(data, 'note', 'Observación', 3, 500, required=False)
    require(result != 'not_met' or note or doc, 'validation', 'Un incumplimiento requiere evidencia (documento) u observación fundada.', 422, {'note': 'Fundá el incumplimiento.'})
    page = inp.integer(data, 'page', 'Página', required=False, minimum=1, maximum=5000)
    quote = inp.text(data, 'quote', 'Fragmento', 1, 600, required=False)
    rv = RequirementReview(offer_id=offer.id, requirement_id=req.id, result=result, treatment=treatment if result == 'not_met' else None,
                           observed_value=inp.text(data, 'observed_value', 'Dato observado', 1, 200, required=False), document_id=doc.id if doc else None,
                           page=page, quote=quote, note=note, reviewer_id=ctx.user.id)
    db.session.add(rv)
    db.session.flush()
    stale = mark_dependents_stale(ctx.case, f'Cambió la revisión del requisito {req.code} de la oferta {offer.id}.')
    return {'type': 'requirement_review', 'id': rv.id, 'reference': req.code, 'reason': f'{req.code}: {result}. {note or ""}'.strip(),
            'details': {'offer_id': offer.id, 'result': result, 'treatment': rv.treatment, 'evaluations_invalidated': stale}}


def _score_form(ctx):
    crit = [{'value': c.code, 'label': f'{c.name} (máx. {dstr(c.weight)})'} for c in (ctx.spec.criteria if ctx.spec else []) if c.type == 'manual']
    return [F.field('offer_id', 'Oferta', 'select', options=_offer_choices(ctx)), F.field('criterion_code', 'Criterio cualitativo', 'select', options=crit),
            F.field('points', 'Puntaje', 'number', help='Entre 0 y el máximo de la escala publicada.'),
            F.field('evidence', 'Evidencia de la aplicación de la escala', 'textarea', rows=3)]


@action('score.record', 'Registrar puntaje cualitativo', 'requirement.review', {'offers_opened', 'evaluation', 'decision'}, form=_score_form,
        blockers=lambda ctx: _data_stage_blockers(ctx) or ([] if any(c.type == 'manual' for c in ctx.spec.criteria) else ['El pliego no tiene criterios cualitativos.']),
        description='Los criterios cualitativos necesitan escala publicada y una evaluación atribuida; no un puntaje espontáneo del modelo de lenguaje.')
def score_record(ctx, data):
    offer = offer_in_case(ctx, data.get('offer_id'))
    code = inp.text(data, 'criterion_code', 'Criterio', 1, 20)
    crit = next((c for c in ctx.spec.criteria if c.code == code and c.type == 'manual'), None)
    require(crit is not None, 'validation', 'Criterio inválido.', 422, {'criterion_code': 'Inválido.'})
    points = inp.decimal(data, 'points', 'Puntaje', positive=False, places=4)
    require(0 <= points <= crit.weight, 'validation', f'El puntaje debe estar entre 0 y {dstr(crit.weight)}.', 422, {'points': 'Fuera de escala.'})
    ms = ManualScore(offer_id=offer.id, criterion_id=crit.id, points=points, evidence=inp.text(data, 'evidence', 'Evidencia', 10, 600), evaluator_id=ctx.user.id)
    db.session.add(ms)
    db.session.flush()
    mark_dependents_stale(ctx.case, f'Cambió el puntaje cualitativo de la oferta {offer.id}.')
    return {'type': 'manual_score', 'id': ms.id, 'reference': code, 'reason': ms.evidence, 'details': {'offer_id': offer.id, 'points': dstr(points)}}


# ---------------------------------------------------------------- subsanación

def _sub_request_form(ctx):
    reqs = [{'value': r.id, 'label': f'{r.code}: {r.text}'} for r in (ctx.spec.requirements if ctx.spec else [])]
    return [F.field('offer_id', 'Oferta', 'select', options=_offer_choices(ctx)), F.field('requirement_id', 'Requisito', 'select', options=reqs),
            F.field('description', 'Qué debe subsanarse', 'textarea', rows=3, help='Solo carencias formales; no habilita negociar la oferta.'),
            F.field('due_date', 'Plazo de respuesta', 'datetime')]


@action('subsanation.request', 'Solicitar subsanación', 'subsanation.manage', {'offers_opened', 'evaluation'}, form=_sub_request_form, blockers=_data_stage_blockers,
        description='Una carencia formal subsanable abre una actuación con plazo; no se confunde con un incumplimiento técnico o comercial.')
def subsanation_request(ctx, data):
    offer = offer_in_case(ctx, data.get('offer_id'))
    req = spec_requirement(ctx.spec, data.get('requirement_id'))
    last = latest_reviews(offer.id).get(req.id)
    require(last is not None and last.result == 'not_met' and last.treatment == 'subsanable', 'blocked',
            'Primero registrá la revisión del requisito como carencia formal subsanable.', 422)
    due = inp.moment(data, 'due_date', 'Plazo')
    require(due > utcnow(), 'validation', 'El plazo debe ser futuro.', 422, {'due_date': 'Debe ser futuro.'})
    s = Subsanation(case_id=ctx.case.id, offer_id=offer.id, requirement_id=req.id, description=inp.text(data, 'description', 'Descripción', 5, 2000),
                    due_at=due, requested_by=ctx.user.id)
    db.session.add(s)
    db.session.flush()
    return {'type': 'subsanation', 'id': s.id, 'reference': req.code, 'reason': s.description, 'details': {'offer_id': offer.id, 'due': iso_utc(due)}}


def _open_subsanations(ctx):
    return db.session.scalars(db.select(Subsanation).where(Subsanation.case_id == ctx.case.id, Subsanation.state == 'open').order_by(Subsanation.id)).all()


@action('subsanation.respond', 'Registrar respuesta de subsanación', 'subsanation.manage', {'offers_opened', 'evaluation'},
        form=lambda ctx: [F.field('subsanation_id', 'Subsanación', 'select', options=[{'value': s.id, 'label': f'#{s.id} · {s.description[:60]}'} for s in _open_subsanations(ctx)]),
                          F.field('response_text', 'Respuesta recibida', 'textarea', rows=3), F.field('document_id', 'Documento recibido', 'document', required=False)],
        blockers=lambda ctx: [] if _open_subsanations(ctx) else ['No hay subsanaciones abiertas.'],
        description='La respuesta es una actuación propia: el original no se borra ni se sobrescribe.')
def subsanation_respond(ctx, data):
    s = db.session.get(Subsanation, inp.integer(data, 'subsanation_id', 'Subsanación', minimum=1))
    require(s is not None and s.case_id == ctx.case.id and s.state == 'open', 'validation', 'Subsanación inválida.', 422, {'subsanation_id': 'Inválida.'})
    doc = doc_in_case(ctx, data.get('document_id'))
    late = utcnow() > s.due_at
    s.response_text, s.response_document_id, s.responded_at = inp.text(data, 'response_text', 'Respuesta', 3, 4000), doc.id if doc else None, utcnow()
    s.state = 'answered'
    mark_dependents_stale(ctx.case, 'Se recibió una respuesta de subsanación.')
    return {'type': 'subsanation', 'id': s.id, 'reason': s.response_text, 'details': {'late': late}}
