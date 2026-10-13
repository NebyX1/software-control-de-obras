"""Carga de documentos: validación de tipo real, hash del original, versiones inmutables y custodia."""
from flask import current_app
from app.extensions import db
from app.infrastructure import audit, tasks
from app.infrastructure.models import Document, DocumentVersion, Envelope
from app.infrastructure.storage import get_document_storage
from app.modules.documents.validation import validate_upload, safe_filename
from app.shared.contracts import utcnow
from app.shared.errors import require

KINDS = ('solicitud', 'pliego', 'oferta', 'anexo_confidencial', 'acta', 'dictamen', 'control', 'resolucion', 'comprobante', 'factura', 'orden', 'constancia', 'otro')
CLASSES = ('public', 'internal', 'confidential')


def store_version(doc, content, filename, user, assignment=None, case=None, enqueue=True):
    max_size = current_app.config['MAX_UPLOAD_MB'] * 1024 * 1024
    info = validate_upload(content, filename, max_size)
    storage = get_document_storage()
    key, sha = storage.put(content)
    version = (db.session.scalar(db.select(db.func.max(DocumentVersion.version)).where(DocumentVersion.document_id == doc.id)) or 0) + 1
    sealed = bool(doc.envelope_id and db.session.get(Envelope, doc.envelope_id).opened_at is None)
    status = 'held_sealed' if sealed else ('held_confidential' if doc.classification == 'confidential' else 'pending')
    ver = DocumentVersion(document_id=doc.id, version=version, storage_key=key, sha256=sha, size=len(content), mime=info['mime'], original_name=safe_filename(filename),
                          text_status=status, page_count=info['page_count'], uploaded_by=user.id)
    db.session.add(ver)
    db.session.flush()
    if status == 'pending':
        if enqueue and info['mime'] in ('application/pdf', 'text/plain'):
            tasks.enqueue('document_ingest', {'document_version_id': ver.id}, case_id=doc.case_id, user_id=user.id, dedupe_key=f'ingest:{ver.id}')
        else:
            ver.text_status = 'no_text'  # imágenes: sin OCR; quedan pendientes de tratamiento manual
    return ver


def create_document(case, user, content, filename, kind, title, classification, envelope=None, external_reference=None, assignment=None):
    require(kind in KINDS, 'validation', 'Tipo de documento inválido.', 422, {'kind': 'Inválido.'})
    require(classification in CLASSES, 'validation', 'Clasificación inválida.', 422, {'classification': 'Inválida.'})
    title = (title or '').strip()
    require(3 <= len(title) <= 255, 'validation', 'El título debe tener entre 3 y 255 caracteres.', 422, {'title': 'Entre 3 y 255.'})
    if envelope is not None:
        require(envelope.case_id == case.id, 'validation', 'Sobre inválido.', 422)
        require(envelope.opened_at is None, 'sealed', 'El sobre ya fue abierto: no se incorporan nuevos originales.', 409)
        if envelope.status == 'received':
            require(utcnow() <= envelope.deadline_at, 'deadline_passed', 'El plazo de recepción venció: no se pueden incorporar originales a este sobre.', 409)
        kind = kind if kind in ('oferta', 'anexo_confidencial') else 'oferta'
        if kind == 'anexo_confidencial':
            classification = 'confidential'
    doc = Document(case_id=case.id, kind=kind, title=title, classification=classification, envelope_id=envelope.id if envelope else None, created_by=user.id,
                   external_reference=external_reference)
    db.session.add(doc)
    db.session.flush()
    ver = store_version(doc, content, filename, user, assignment, case) if content is not None else None
    audit.record(user, 'document.upload', 'document', doc.id, case=case, reason=title, reference=ver.sha256[:16] if ver else external_reference,
                 details={'kind': kind, 'classification': classification, 'sealed': bool(envelope), 'mime': ver.mime if ver else None, 'size': ver.size if ver else None,
                          'sha256': ver.sha256 if ver else None, 'version': ver.version if ver else None, 'envelope_id': envelope.id if envelope else None},
                 role_code=assignment.role_code if assignment else None, assignment_id=assignment.id if assignment else None)
    return doc, ver
