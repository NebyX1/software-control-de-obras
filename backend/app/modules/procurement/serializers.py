"""Serialización de expedientes. Aplica las reglas de visibilidad: nada reservado sale hacia el navegador."""
from app.extensions import db
from app.infrastructure.models import *  # noqa: F401,F403
from app.modules.documents.policies import can_read_content, can_see_metadata, is_sealed
from app.modules.evaluation import service as evals
from app.modules.identity.permissions import find_assignment, active_assignments
from app.modules.procurement import framework
from app.modules.procurement.actions.common import current_round, effective_deadline
from app.modules.procurement.states import STAGES, STATUS_LABEL, STATUS_TONE
from app.modules.rules.service import PROCEDURE_LABELS
from app.shared.contracts import dstr, iso_utc, to_local


class Names:
    def __init__(self):
        self.cache = {}

    def __call__(self, user_id):
        if user_id is None:
            return None
        if user_id not in self.cache:
            u = db.session.get(User, user_id)
            self.cache[user_id] = u.full_name if u else None
        return self.cache[user_id]


def case_summary(case):
    return {'code': case.code, 'title': case.title, 'area': case.area.name if case.area else None, 'area_id': case.area_id, 'status': case.status,
            'status_label': STATUS_LABEL.get(case.status, case.status), 'tone': STATUS_TONE.get(case.status, 'neutral'), 'stage': case.stage,
            'stage_label': STAGES[case.stage], 'estimated_total': dstr(case.estimated_total), 'currency': case.currency,
            'procedure_type': case.procedure_type, 'procedure_label': PROCEDURE_LABELS.get(case.procedure_type) if case.procedure_type else None,
            'suggested_procedure': ((case.procedure_basis or {}).get('suggestion') or {}).get('label'), 'is_demo': bool(case.is_demo),
            'updated_at': iso_utc(case.updated_at), 'created_at': iso_utc(case.created_at), 'version': case.version}


def _doc_json(doc, user, case, assignments):
    sealed = is_sealed(doc)
    if not can_see_metadata(user, doc, case, assignments):
        return None
    readable = can_read_content(user, doc, case, assignments)
    return {'id': doc.id, 'kind': doc.kind, 'title': doc.title, 'classification': doc.classification, 'sealed': sealed, 'envelope_id': doc.envelope_id,
            'can_download': readable, 'external_reference': doc.external_reference, 'created_at': iso_utc(doc.created_at),
            'versions': [{'version': v.version, 'sha256': v.sha256, 'size': v.size, 'mime': v.mime, 'original_name': v.original_name,
                          'text_status': v.text_status, 'page_count': v.page_count, 'uploaded_at': iso_utc(v.uploaded_at)} for v in doc.versions]}


def spec_json(spec):
    return {'id': spec.id, 'version': spec.version, 'status': spec.status, 'mode': spec.mode, 'currency': spec.currency, 'fx': spec.fx or {},
            'minimum_text': spec.minimum_text, 'delivery_terms': spec.delivery_terms, 'flags': spec.flags or {}, 'similarity_margin': dstr(spec.similarity_margin),
            'offer_deadline': iso_utc(spec.offer_deadline), 'reception_channel': spec.reception_channel, 'reception_place': spec.reception_place,
            'change_reason': spec.change_reason, 'content_hash': spec.content_hash, 'approved_at': iso_utc(spec.approved_at), 'created_at': iso_utc(spec.created_at),
            'requirements': [{'id': r.id, 'code': r.code, 'text': r.text, 'essential': r.essential, 'kind': r.kind, 'attribute': r.attribute, 'operator': r.operator,
                              'threshold': dstr(r.threshold) if r.threshold is not None else None, 'unit': r.unit} for r in spec.requirements],
            'criteria': [{'id': c.id, 'code': c.code, 'name': c.name, 'weight': dstr(c.weight), 'type': c.type, 'attribute': c.attribute, 'scale': c.scale or [],
                          'description': c.description} for c in spec.criteria]}


def _offer_json(offer, names):
    data = db.session.scalar(db.select(OfferDataVersion).where(OfferDataVersion.offer_id == offer.id, OfferDataVersion.version == offer.data_version)) if offer.data_version else None
    reviews = evals.latest_reviews(offer.id)
    scores = evals.latest_manual_scores(offer.id)
    return {'id': offer.id, 'supplier_id': offer.supplier_id, 'supplier': offer.supplier.name, 'currency': offer.currency, 'status': offer.status,
            'data_version': offer.data_version,
            'data': None if not data else {'prices_include_tax': data.prices_include_tax, 'freight': dstr(data.freight), 'freight_includes_tax': data.freight_includes_tax,
                                           'freight_tax_rate': dstr(data.freight_tax_rate), 'discount_total': dstr(data.discount_total), 'delivery_days': data.delivery_days,
                                           'warranty_months': data.warranty_months, 'delivery_terms': data.delivery_terms, 'reason': data.reason,
                                           'recorded_by': names(data.recorded_by), 'recorded_at': iso_utc(data.created_at),
                                           'lines': [{'request_line_id': l.request_line_id, 'unit_price': dstr(l.unit_price), 'tax_rate': dstr(l.tax_rate),
                                                      'discount': dstr(l.discount), 'quantity': dstr(l.quantity) if l.quantity is not None else None} for l in data.lines]},
            'reviews': [{'requirement_id': r.requirement_id, 'result': r.result, 'treatment': r.treatment, 'observed_value': r.observed_value, 'document_id': r.document_id,
                         'page': r.page, 'quote': r.quote, 'note': r.note, 'reviewer': names(r.reviewer_id), 'reviewed_at': iso_utc(r.reviewed_at)} for r in reviews.values()],
            'manual_scores': [{'criterion_id': k, 'points': dstr(m.points), 'evidence': m.evidence, 'evaluator': names(m.evaluator_id)} for k, m in scores.items()]}


def _evaluation_json(ev):
    return {'id': ev.id, 'version': ev.version, 'status': ev.status, 'stale_reason': ev.stale_reason, 'mode': ev.mode, 'engine_version': ev.engine_version,
            'input_hash': ev.input_hash, 'spec_version_id': ev.spec_version_id, 'created_at': iso_utc(ev.created_at), 'result': ev.result,
            'recommended_offer_id': ev.recommended_offer_id}


def case_detail(user, case, with_actions=True):
    names = Names()
    assignments = active_assignments(user)
    ctx = framework.Ctx(case, user, assignments)
    spec = ctx.spec
    out = case_summary(case)
    sel = lambda m, *w: db.session.scalars(db.select(m).where(*w)).all()
    can = lambda perm: find_assignment(user, perm, case.area_id, assignments) is not None
    out.update({
        'id': case.id, 'need_text': case.need_text, 'delivery_place': case.delivery_place, 'requester': names(case.requester_id), 'procedure_basis': case.procedure_basis,
        'branch': case.branch, 'flags': case.flags, 'round': current_round(case), 'submitted_at': iso_utc(case.submitted_at), 'closed_at': iso_utc(case.closed_at),
        'stages': STAGES,
        'lines': [{'id': l.id, 'position': l.position, 'description': l.description, 'quantity': dstr(l.quantity), 'unit': l.unit,
                   'estimated_unit_price': dstr(l.estimated_unit_price) if l.estimated_unit_price is not None else None,
                   'tax_rate': dstr(l.tax_rate) if l.tax_rate is not None else None} for l in ctx.lines],
        'spec': spec_json(spec) if spec else None,
        'spec_versions': [{'id': s.id, 'version': s.version, 'status': s.status, 'approved_at': iso_utc(s.approved_at), 'change_reason': s.change_reason}
                          for s in sel(SpecVersion, SpecVersion.case_id == case.id)],
    })
    av = sel(Availability, Availability.case_id == case.id)
    out['availabilities'] = [{'id': a.id, 'amount': dstr(a.amount), 'fiscal_year': a.fiscal_year, 'budget_item': a.budget_item, 'funding_source': a.funding_source,
                              'availability_date': a.availability_date.isoformat(), 'support_ref': a.support_ref, 'status': a.status, 'registered_by': names(a.registered_by),
                              'covers_estimate': a.amount >= case.estimated_total} for a in av]
    out['authorizations'] = [{'id': a.id, 'kind': a.kind, 'spec_version_id': a.spec_version_id, 'reference': a.reference, 'grounds': a.grounds, 'by': names(a.authorized_by),
                              'at': iso_utc(a.created_at)} for a in sel(CaseAuthorization, CaseAuthorization.case_id == case.id)]
    out['publicity'] = [{'id': p.id, 'kind': p.kind, 'state': p.state, 'reference': p.reference, 'published_at': iso_utc(p.published_at), 'note': p.notice_note,
                         'by': names(p.created_by)} for p in sel(PublicityRecord, PublicityRecord.case_id == case.id)]
    deadline = effective_deadline(case, spec) if spec else None
    out['reception'] = {'deadline': iso_utc(deadline), 'deadline_local': to_local(deadline).isoformat() if deadline else None, 'timezone': 'America/Montevideo',
                        'channel': spec.reception_channel if spec else None, 'place': spec.reception_place if spec else None,
                        'extensions': [{'previous': iso_utc(e.previous_deadline), 'new': iso_utc(e.new_deadline), 'reason': e.reason, 'communicated_ref': e.communicated_ref,
                                        'at': iso_utc(e.created_at)} for e in sel(DeadlineExtension, DeadlineExtension.case_id == case.id)]}
    sees_envelopes = can('envelope.register') or can('offer.read')
    envs = sel(Envelope, Envelope.case_id == case.id) if sees_envelopes else []
    out['envelopes'] = [{'id': e.id, 'receipt_code': e.receipt_code, 'supplier': e.supplier.name, 'channel': e.channel, 'received_at': iso_utc(e.received_at),
                         'on_time': e.on_time, 'status': e.status, 'opened': e.opened_at is not None, 'custody_note': e.custody_note, 'round': e.round} for e in envs]
    op = sel(OpeningRecord, OpeningRecord.case_id == case.id)
    out['openings'] = [{'reference': o.reference, 'opened_at': iso_utc(o.opened_at), 'participants': o.participants, 'envelope_count': o.envelope_count, 'round': o.round} for o in op]
    opened = any(o.round == current_round(case) for o in op) or any(e.channel == 'convenio_marco' and e.opened_at is not None for e in envs)
    sees_offers = can('offer.read') and opened
    out['offers'] = [_offer_json(o, names) for o in sel(Offer, Offer.case_id == case.id)
                     if db.session.get(Envelope, o.envelope_id).opened_at is not None] if sees_offers else []
    out['offers_sealed'] = bool(envs) and not opened
    out['subsanations'] = [{'id': s.id, 'offer_id': s.offer_id, 'requirement_id': s.requirement_id, 'description': s.description, 'due_at': iso_utc(s.due_at), 'state': s.state,
                            'response_text': s.response_text} for s in sel(Subsanation, Subsanation.case_id == case.id)] if sees_offers else []
    evs = sel(Evaluation, Evaluation.case_id == case.id) if can('evaluation.read') and opened else []
    cur = next((e for e in sorted(evs, key=lambda e: -e.version) if e.status in ('current', 'stale')), None)
    out['evaluation'] = _evaluation_json(cur) if cur else None
    out['evaluations'] = [{'id': e.id, 'version': e.version, 'status': e.status, 'created_at': iso_utc(e.created_at), 'recommended_offer_id': e.recommended_offer_id,
                           'stale_reason': e.stale_reason} for e in sorted(evs, key=lambda e: -e.version)]
    out['opinions'] = [{'id': o.id, 'evaluation_id': o.evaluation_id, 'recommended_offer_id': o.recommended_offer_id, 'reference': o.reference, 'grounds': o.grounds,
                        'author': names(o.author_id), 'status': o.status, 'at': iso_utc(o.created_at)} for o in sel(Opinion, Opinion.case_id == case.id)] if opened else []
    ivs = sel(Intervention, Intervention.case_id == case.id)
    resp = {r.intervention_id: r for r in db.session.scalars(db.select(ObservationResponse).where(ObservationResponse.intervention_id.in_([i.id for i in ivs] or [0])))}
    out['interventions'] = [{'id': i.id, 'kind': i.kind, 'result': i.result, 'reference': i.reference, 'reason': i.reason, 'offer_id': i.offer_id, 'invoice_id': i.invoice_id,
                             'status': i.status, 'author': names(i.author_id), 'at': iso_utc(i.created_at),
                             'response': None if i.id not in resp else {'reference': resp[i.id].reference, 'reason': resp[i.id].reason, 'by': names(resp[i.id].author_id),
                                                                       'at': iso_utc(resp[i.id].created_at)}} for i in ivs] if opened or ivs else []
    aw = db.session.scalar(db.select(Award).where(Award.case_id == case.id, Award.status == 'active'))
    out['award'] = None if not aw else {'id': aw.id, 'offer_id': aw.offer_id, 'supplier': db.session.get(Offer, aw.offer_id).supplier.name, 'amount': dstr(aw.amount),
                                        'currency': aw.currency, 'reference': aw.reference, 'grounds': aw.grounds, 'departure_reason': aw.departure_reason,
                                        'authority': aw.authority_snapshot, 'evaluation_id': aw.evaluation_id, 'offer_data_version': aw.offer_data_version,
                                        'at': iso_utc(aw.created_at)}
    out['communications'] = [{'id': c.id, 'kind': c.kind, 'state': c.state, 'reference': c.reference, 'recipients': c.recipients, 'at': iso_utc(c.created_at)}
                             for c in sel(Communication, Communication.case_id == case.id)]
    ct = db.session.scalar(db.select(Contract).where(Contract.case_id == case.id))
    out['contract'] = None if not ct else {'status': ct.status, 'reference': ct.reference, 'reason_not_required': ct.reason_not_required}
    out['guarantees'] = [{'id': g.id, 'kind': g.kind, 'amount': dstr(g.amount) if g.amount is not None else None, 'due_date': g.due_date.isoformat() if g.due_date else None,
                          'status': g.status, 'reference': g.reference} for g in sel(Guarantee, Guarantee.case_id == case.id)]
    order = db.session.scalar(db.select(PurchaseOrder).where(PurchaseOrder.case_id == case.id, PurchaseOrder.status == 'active'))
    out['order'] = None if not order else {'id': order.id, 'code': order.code, 'version': order.version, 'total': dstr(order.total), 'currency': order.currency,
                                           'issued_at': iso_utc(order.issued_at), 'supplier': db.session.get(Supplier, order.supplier_id).name,
                                           'lines': [{'id': l.id, 'description': l.description, 'unit': l.unit, 'quantity': dstr(l.quantity), 'unit_price': dstr(l.unit_price),
                                                      'tax_rate': dstr(l.tax_rate), 'amount': dstr(l.amount), 'accepted_qty': dstr(l.accepted_qty),
                                                      'rejected_qty': dstr(l.rejected_qty), 'invoiced_qty': dstr(l.invoiced_qty)} for l in order.lines]}
    out['receipts'] = [{'id': r.id, 'reference': r.reference, 'received_at': iso_utc(r.received_at), 'by': names(r.received_by), 'notes': r.notes,
                        'lines': [{'order_line_id': l.order_line_id, 'accepted_qty': dstr(l.accepted_qty), 'rejected_qty': dstr(l.rejected_qty), 'reject_reason': l.reject_reason}
                                  for l in r.lines]} for r in sel(Receipt, Receipt.case_id == case.id)]
    invoices = sel(Invoice, Invoice.case_id == case.id)
    out['invoices'] = [{'id': i.id, 'doc_type': i.doc_type, 'series': i.series, 'number': i.number, 'issue_date': i.issue_date.isoformat(), 'currency': i.currency,
                        'total': dstr(i.total), 'adjustment_total': dstr(i.adjustment_total), 'authorized_amount': dstr(i.authorized_amount), 'paid_amount': dstr(i.paid_amount),
                        'status': i.status, 'steps': [{'step': s.step, 'reference': s.reference, 'by': names(s.author_id), 'amount': dstr(s.amount) if s.amount is not None else None,
                                                      'at': iso_utc(s.created_at)} for s in db.session.scalars(db.select(InvoiceStep).where(InvoiceStep.invoice_id == i.id).order_by(InvoiceStep.id))]}
                       for i in invoices]
    out['payments'] = [{'id': p.id, 'invoice_id': p.invoice_id, 'amount': dstr(p.amount), 'proof_reference': p.proof_reference, 'executed_on': p.executed_on.isoformat(),
                        'mode': p.execution_mode, 'by': names(p.recorded_by)} for p in sel(Payment, Payment.case_id == case.id)]
    out['modifications'] = [{'id': m.id, 'sequence': m.sequence, 'kind': m.kind, 'status': m.status, 'grounds': m.grounds, 'changes': m.changes, 'limit_check': m.limit_check}
                            for m in sel(ContractModification, ContractModification.case_id == case.id)]
    cl = db.session.scalar(db.select(CaseClosure).where(CaseClosure.case_id == case.id))
    out['closure'] = None if not cl else {'reference': cl.reference, 'reason': cl.reason, 'pending_obligations': cl.pending_obligations, 'at': iso_utc(cl.closed_at)}
    out['branches'] = [{'id': b.id, 'kind': b.kind, 'state': b.state, 'reason': b.reason, 'reference': b.reference, 'detail': b.detail, 'at': iso_utc(b.created_at)}
                       for b in sel(BranchRecord, BranchRecord.case_id == case.id)]
    docs = db.session.scalars(db.select(Document).where(Document.case_id == case.id, Document.status == 'active').order_by(Document.id)).all()
    out['documents'] = [d for d in (_doc_json(x, user, case, assignments) for x in docs) if d]
    out['preparation'] = {'availability': any(a.status == 'active' for a in av),
                          'spec_approved': bool(spec and spec.status == 'approved'),
                          'call_authorized': any(a['spec_version_id'] == (spec.id if spec else 0) for a in out['authorizations']),
                          'publicity': any(p['state'] != 'pending' for p in out['publicity']), 'classified': case.procedure_type is not None}
    out['recent_events'] = events_json(case.id, 8, names)
    if with_actions:
        acts = framework.available_actions(ctx)
        main = framework.main_action(ctx, acts)
        out['actions'] = acts
        out['next'] = None if main is None else {'action': main['name'], 'label': main['label'], 'responsible': main['responsible'], 'can': main['can'], 'blockers': main['blockers']}
        out['can_edit_draft'] = case.status == 'draft' and can('case.edit_draft')
    return out


def events_json(case_id, limit=50, names=None, before_id=None):
    q = db.select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.id.desc()).limit(limit)
    if before_id:
        q = q.where(AuditEvent.id < before_id)
    return [event_json(e) for e in db.session.scalars(q)]


def event_json(e):
    return {'id': e.id, 'at': iso_utc(e.created_at), 'actor': e.actor_name, 'role': e.role_code, 'action': e.action, 'resource_type': e.resource_type,
            'resource_id': e.resource_id, 'version': e.resource_version, 'reason': e.reason, 'reference': e.reference, 'hash': e.hash}
