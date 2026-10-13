"""Política de acceso a documentos: es la ÚNICA fuente de verdad para API, descargas, búsqueda, exportación e IA.

Antes de la apertura autorizada, el contenido de un sobre no es legible por ningún usuario (ni siquiera por quien lo
registró); solo se exponen metadatos de custodia a quienes pueden registrar sobres. Tras la apertura se aplica
`offer.read`, y los anexos confidenciales exigen `offer.read_confidential`.
"""
from app.extensions import db
from app.infrastructure.models import Document, Envelope
from app.modules.identity.permissions import find_assignment, active_assignments
from app.modules.procurement.access import can_read_case


def envelope_of(doc):
    return db.session.get(Envelope, doc.envelope_id) if doc.envelope_id else None


def is_sealed(doc, envelope=None):
    if not doc.envelope_id:
        return False
    env = envelope or envelope_of(doc)
    return env is not None and env.opened_at is None


def can_read_content(user, doc, case, assignments=None, envelope=None):
    if doc.status != 'active' or not can_read_case(user, case, assignments):
        return False
    a = assignments if assignments is not None else active_assignments(user)
    if find_assignment(user, 'document.read', case.area_id, a) is None:
        return False
    if doc.envelope_id:
        if is_sealed(doc, envelope):
            return False
        if find_assignment(user, 'offer.read', case.area_id, a) is None:
            return False
    if doc.classification == 'confidential':
        return find_assignment(user, 'offer.read_confidential', case.area_id, a) is not None
    return True


def can_see_metadata(user, doc, case, assignments=None):
    if not can_read_case(user, case, assignments):
        return False
    a = assignments if assignments is not None else active_assignments(user)
    if doc.envelope_id:
        return (find_assignment(user, 'envelope.register', case.area_id, a) is not None
                or find_assignment(user, 'offer.read', case.area_id, a) is not None)
    return find_assignment(user, 'document.read', case.area_id, a) is not None


def readable_document_ids(user, case):
    """Identificadores de documentos activos cuyo contenido puede leer el usuario (base de la recuperación para IA)."""
    a = active_assignments(user)
    out = []
    for doc in db.session.scalars(db.select(Document).where(Document.case_id == case.id, Document.status == 'active')):
        if can_read_content(user, doc, case, a):
            out.append(doc.id)
    return out
