"""Utilidades comunes a los manejadores de acciones."""
from app.extensions import db
from app.infrastructure.models import Document, Offer, Supplier, SpecRequirement
from app.modules.procurement import inputs as inp
from app.shared.errors import require


def doc_in_case(ctx, document_id, required=False, label='Documento'):
    if document_id in (None, ''):
        require(not required, 'validation', f'{label}: es obligatorio.', 422, {'document_id': 'Adjuntá un documento del expediente.'})
        return None
    try:
        doc = db.session.get(Document, int(document_id))
    except (TypeError, ValueError):
        doc = None
    require(doc is not None and doc.case_id == ctx.case.id and doc.status == 'active', 'validation',
            f'{label}: el documento no pertenece a este expediente.', 422, {'document_id': 'Documento inválido.'})
    return doc


def offer_in_case(ctx, offer_id):
    offer = db.session.get(Offer, inp.integer({'v': offer_id}, 'v', 'Oferta', minimum=1))
    require(offer is not None and offer.case_id == ctx.case.id, 'validation', 'Oferta inválida para este expediente.', 422, {'offer_id': 'Oferta inválida.'})
    return offer


def spec_requirement(spec, requirement_id):
    req = db.session.get(SpecRequirement, inp.integer({'v': requirement_id}, 'v', 'Requisito', minimum=1))
    require(req is not None and req.spec_version_id == spec.id, 'validation', 'El requisito no pertenece al pliego vigente.', 422, {'requirement_id': 'Requisito inválido.'})
    return req


def effective_deadline(case, spec):
    from app.infrastructure.models import DeadlineExtension
    ext = db.session.scalars(db.select(DeadlineExtension).where(DeadlineExtension.case_id == case.id).order_by(DeadlineExtension.id.desc())).first()
    if ext:
        return ext.new_deadline
    return spec.offer_deadline if spec else None


def current_round(case):
    return (case.flags or {}).get('round', 1)


def supplier_choices():
    rows = db.session.scalars(db.select(Supplier).where(Supplier.active.is_(True)).order_by(Supplier.name)).all()
    return [{'value': s.id, 'label': f'{s.name}' + (f' · {s.tax_id}' if s.tax_id else '')} for s in rows]
