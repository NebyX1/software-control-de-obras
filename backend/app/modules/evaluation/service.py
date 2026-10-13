"""Construcción de entradas del motor desde datos validados, persistencia versionada y obsolescencia de dependientes."""
from decimal import Decimal
from app.extensions import db
from app.infrastructure.models import (Offer, OfferDataVersion, Envelope, RequirementReview, ManualScore, Evaluation, Opinion, Intervention,
                                       DocumentVersion, Document)
from app.modules.evaluation import engine
from app.shared.contracts import canonical_hash, dstr, utcnow


def latest_reviews(offer_id):
    rows = db.session.scalars(db.select(RequirementReview).where(RequirementReview.offer_id == offer_id).order_by(RequirementReview.id)).all()
    return {r.requirement_id: r for r in rows}


def latest_manual_scores(offer_id):
    rows = db.session.scalars(db.select(ManualScore).where(ManualScore.offer_id == offer_id).order_by(ManualScore.id)).all()
    return {r.criterion_id: r for r in rows}


def evaluable_offers(case):
    current_round = (case.flags or {}).get('round', 1)
    q = (db.select(Offer, Envelope).join(Envelope, Envelope.id == Offer.envelope_id)
         .where(Offer.case_id == case.id, Envelope.opened_at.is_not(None), Envelope.status == 'received', Envelope.round == current_round)
         .order_by(Offer.id))
    return db.session.execute(q).all()


def build_input(case, spec, lines):
    offers, doc_versions = [], {}
    for offer, env in evaluable_offers(case):
        data = (db.session.scalar(db.select(OfferDataVersion).where(OfferDataVersion.offer_id == offer.id, OfferDataVersion.version == offer.data_version))
                if offer.data_version else None)
        reviews = latest_reviews(offer.id)
        scores = latest_manual_scores(offer.id)
        item = {'id': offer.id, 'name': offer.supplier.name, 'currency': offer.currency, 'data_version': offer.data_version,
                'lines': [], 'attributes': {}, 'reviews': {}, 'manual_scores': {}}
        if data:
            item.update({'currency': data.currency, 'prices_include_tax': data.prices_include_tax, 'freight': dstr(data.freight),
                         'freight_includes_tax': data.freight_includes_tax, 'freight_tax_rate': dstr(data.freight_tax_rate),
                         'discount_total': dstr(data.discount_total), 'delivery_terms': data.delivery_terms})
            item['lines'] = [{'line_id': l.request_line_id, 'unit_price': dstr(l.unit_price), 'tax_rate': dstr(l.tax_rate),
                              'discount': dstr(l.discount), 'quantity': dstr(l.quantity) if l.quantity is not None else None} for l in data.lines]
            if data.delivery_days is not None:
                item['attributes']['delivery_days'] = data.delivery_days
            if data.warranty_months is not None:
                item['attributes']['warranty_months'] = data.warranty_months
        for req in spec.requirements:
            r = reviews.get(req.id)
            if r:
                item['reviews'][str(req.id)] = {'result': r.result, 'treatment': r.treatment, 'observed': r.observed_value,
                                                'reviewer_id': r.reviewer_id, 'review_id': r.id}
        for crit in spec.criteria:
            m = scores.get(crit.id)
            if m:
                item['manual_scores'][crit.code] = {'points': dstr(m.points), 'evaluator': str(m.evaluator_id), 'evidence': m.evidence}
        offers.append(item)
        versions = db.session.execute(
            db.select(DocumentVersion.id, DocumentVersion.sha256).join(Document, Document.id == DocumentVersion.document_id)
            .where(Document.envelope_id == env.id, Document.status == 'active')).all()
        doc_versions[str(offer.id)] = [{'id': v[0], 'sha256': v[1]} for v in versions]
    return {
        'mode': spec.mode, 'currency': spec.currency, 'fx': spec.fx or {}, 'delivery_terms': spec.delivery_terms,
        'similarity_margin': dstr(Decimal(spec.similarity_margin)), 'flags': spec.flags or {},
        'lines': [{'id': l.id, 'position': l.position, 'quantity': dstr(l.quantity)} for l in lines],
        'requirements': [{'id': r.id, 'code': r.code, 'text': r.text, 'essential': r.essential, 'kind': r.kind, 'attribute': r.attribute,
                          'operator': r.operator, 'threshold': dstr(r.threshold) if r.threshold is not None else None} for r in spec.requirements],
        'criteria': [{'code': c.code, 'name': c.name, 'weight': dstr(c.weight), 'type': c.type, 'attribute': c.attribute,
                      'scale': c.scale or []} for c in spec.criteria],
        'offers': offers,
        'traceability': {'spec_version': spec.version, 'spec_hash': spec.content_hash, 'documents': doc_versions},
    }


def preview(case, spec, lines):
    inp = build_input(case, spec, lines)
    clean = {k: v for k, v in inp.items() if k != 'traceability'}
    return inp, engine.evaluate(clean)


def current_evaluation(case_id):
    return db.session.scalar(db.select(Evaluation).where(Evaluation.case_id == case_id, Evaluation.status == 'current').order_by(Evaluation.version.desc()))


def persist(case, spec, lines, user):
    inp, result = preview(case, spec, lines)
    clean = {k: v for k, v in inp.items() if k != 'traceability'}
    version = (db.session.scalar(db.select(db.func.max(Evaluation.version)).where(Evaluation.case_id == case.id)) or 0) + 1
    for old in db.session.scalars(db.select(Evaluation).where(Evaluation.case_id == case.id, Evaluation.status.in_(('current', 'stale')))):
        old.status = 'superseded'
    ev = Evaluation(case_id=case.id, version=version, spec_version_id=spec.id, mode=spec.mode, engine_version=engine.ENGINE_VERSION,
                    input_hash=canonical_hash(clean), inputs=inp, result=result, recommended_offer_id=result['recommended_offer_id'],
                    created_by=user.id)
    db.session.add(ev)
    db.session.flush()
    return ev


def inputs_unchanged(case, spec, lines, ev):
    inp = build_input(case, spec, lines)
    clean = {k: v for k, v in inp.items() if k != 'traceability'}
    return canonical_hash(clean) == ev.input_hash


def mark_dependents_stale(case, reason):
    """Una edición posterior invalida el resultado y las revisiones que dependían de él, sin borrar su historia."""
    n = 0
    for ev in db.session.scalars(db.select(Evaluation).where(Evaluation.case_id == case.id, Evaluation.status == 'current')):
        ev.status, ev.stale_reason, ev.stale_at = 'stale', reason[:290], utcnow()
        n += 1
    for op in db.session.scalars(db.select(Opinion).where(Opinion.case_id == case.id, Opinion.status == 'active')):
        op.status = 'outdated'
    for iv in db.session.scalars(db.select(Intervention).where(Intervention.case_id == case.id, Intervention.kind == 'control_gasto', Intervention.status == 'active')):
        iv.status = 'outdated'
    return n
