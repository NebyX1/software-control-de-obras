"""Ingesta documental en tareas persistentes: texto por página → fragmentos → embeddings. Solo para documentos habilitados."""
from flask import current_app
from app.extensions import db
from app.infrastructure.models import Document, DocumentVersion, DocumentPage, DocumentChunk, Envelope, ProcurementCase
from app.infrastructure.storage import get_document_storage
from app.ai.rag.chunking import chunk_pages
from app.ai.rag.embedder import embed, to_blob
from app.modules.documents.validation import run_inspect


def ingest_document_version(version_id):
    ver = db.session.get(DocumentVersion, version_id)
    if ver is None:
        return {'status': 'missing'}
    doc = db.session.get(Document, ver.document_id)
    case = db.session.get(ProcurementCase, doc.case_id)
    env = db.session.get(Envelope, doc.envelope_id) if doc.envelope_id else None
    # Autorización al ingerir: nada reservado ni confidencial se extrae, indexa ni envía al proveedor.
    if env is not None and env.opened_at is None:
        ver.text_status = 'held_sealed'
        db.session.commit()
        return {'status': 'held_sealed'}
    if doc.classification == 'confidential':
        ver.text_status = 'held_confidential'
        db.session.commit()
        return {'status': 'held_confidential'}
    if doc.status != 'active':
        return {'status': 'inactive'}
    content = get_document_storage().read(ver.storage_key)
    info = run_inspect(content, True, timeout=30, max_size=current_app.config['MAX_UPLOAD_MB'] * 1024 * 1024)
    pages = [p for p in info['pages'] if p['text'].strip()]
    for old in db.session.scalars(db.select(DocumentChunk).where(DocumentChunk.document_version_id == ver.id)):
        db.session.delete(old)
    for old in db.session.scalars(db.select(DocumentPage).where(DocumentPage.document_version_id == ver.id)):
        db.session.delete(old)
    db.session.flush()
    if sum(len(p['text'].strip()) for p in pages) < 15:
        ver.text_status = 'no_text'  # sin texto utilizable: pendiente de tratamiento (no se simula una lectura)
        db.session.commit()
        return {'status': 'no_text'}
    for p in info['pages']:
        db.session.add(DocumentPage(document_version_id=ver.id, page=p['page'], text=p['text']))
    chunks = chunk_pages(pages)
    vecs = embed([f'{doc.title}\n{c["text"]}' for c in chunks])
    for i, (c, v) in enumerate(zip(chunks, vecs)):
        db.session.add(DocumentChunk(corpus='case', document_version_id=ver.id, document_id=doc.id, case_id=case.id, label=doc.title[:200], seq=i, page_from=c['page_from'],
                                     page_to=c['page_to'], text=c['text'], embedding=to_blob(v), classification=doc.classification, status='active'))
    ver.text_status, ver.page_count = 'extracted', len(info['pages'])
    db.session.commit()
    return {'status': 'extracted', 'chunks': len(chunks)}


def retire_document(doc_id):
    """Retira de inmediato los fragmentos de un documento (la limpieza física puede ser posterior)."""
    for c in db.session.scalars(db.select(DocumentChunk).where(DocumentChunk.document_id == doc_id)):
        c.status = 'retired'
