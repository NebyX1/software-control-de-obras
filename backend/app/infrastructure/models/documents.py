"""Documentos versionados con hash, texto por página y fragmentos recuperables."""
from sqlalchemy.dialects.mysql import LONGTEXT, LONGBLOB
from app.extensions import db
from .base import ts, ts_null, fk


class Document(db.Model):
    __tablename__ = 'document'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id', nullable=True)
    kind = db.Column(db.String(30), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    classification = db.Column(db.String(20), nullable=False, default='internal')  # public | internal | confidential
    # Vínculo opcional con la entidad dueña (p. ej. sobre): determina la reserva hasta la apertura.
    envelope_id = fk('envelope.id', nullable=True)
    status = db.Column(db.String(12), nullable=False, default='active')
    external_reference = db.Column(db.String(300))  # referencia externa verificable, distinta de un archivo
    created_by = fk('user.id')
    created_at = ts()
    versions = db.relationship('DocumentVersion', backref='document', order_by='DocumentVersion.version', lazy='select')


class DocumentVersion(db.Model):
    __tablename__ = 'document_version'
    id = db.Column(db.Integer, primary_key=True)
    document_id = fk('document.id')
    version = db.Column(db.Integer, nullable=False)
    storage_key = db.Column(db.String(100), unique=True, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    size = db.Column(db.Integer, nullable=False)
    mime = db.Column(db.String(80), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    text_status = db.Column(db.String(20), nullable=False, default='pending')
    # pending | extracted | no_text | failed | held_sealed
    page_count = db.Column(db.Integer)
    uploaded_by = fk('user.id')
    uploaded_at = ts()
    __table_args__ = (db.UniqueConstraint('document_id', 'version', name='uq_document_version'),)


class DocumentPage(db.Model):
    __tablename__ = 'document_page'
    id = db.Column(db.Integer, primary_key=True)
    document_version_id = fk('document_version.id', ondelete='CASCADE')
    page = db.Column(db.Integer, nullable=False)
    text = db.Column(LONGTEXT, nullable=False)
    __table_args__ = (db.UniqueConstraint('document_version_id', 'page', name='uq_doc_page'),)


class DocumentChunk(db.Model):
    """Fragmento recuperable. `status=retired` lo excluye de inmediato aunque el índice no se haya limpiado."""
    __tablename__ = 'document_chunk'
    id = db.Column(db.Integer, primary_key=True)
    corpus = db.Column(db.String(20), nullable=False, index=True)  # case | normative
    document_version_id = fk('document_version.id', nullable=True, ondelete='CASCADE')
    document_id = fk('document.id', nullable=True)
    case_id = fk('procurement_case.id', nullable=True)
    normative_source_id = fk('normative_source.id', nullable=True)
    label = db.Column(db.String(200))
    seq = db.Column(db.Integer, nullable=False)
    page_from = db.Column(db.Integer)
    page_to = db.Column(db.Integer)
    section = db.Column(db.String(255))
    text = db.Column(db.Text, nullable=False)
    embedding = db.Column(LONGBLOB)
    classification = db.Column(db.String(20), nullable=False, default='internal')
    status = db.Column(db.String(10), nullable=False, default='active')
    scope = db.Column(db.String(80))
    validity = db.Column(db.String(80))
    created_at = ts()
