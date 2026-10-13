"""Rutas de documentos: carga, nueva versión y descarga autorizada."""
from flask import Blueprint, jsonify, request, Response
from flask_login import current_user
from app.extensions import db
from app.infrastructure import audit
from app.infrastructure.models import Document, DocumentVersion, Envelope, ProcurementCase
from app.infrastructure.storage import get_document_storage
from app.modules.documents.policies import can_read_content, can_see_metadata
from app.modules.documents.service import create_document, store_version
from app.modules.identity.permissions import find_assignment
from app.modules.identity.service import auth_required, rate_limit
from app.modules.procurement.access import get_case
from app.modules.procurement.serializers import _doc_json
from app.modules.identity.permissions import active_assignments
from app.shared.errors import ApiError, require

bp = Blueprint('documents', __name__, url_prefix='/api/v1')


def _form_file():
    f = request.files.get('file')
    require(f is not None and f.filename, 'file_required', 'Seleccioná un archivo.', 422, {'file': 'Obligatorio.'})
    content = f.read()
    return content, f.filename


@bp.post('/cases/<code>/documents')
@auth_required
def upload(code):
    rate_limit('upload', 30)
    case = get_case(current_user, code)
    envelope_id = request.form.get('envelope_id')
    envelope = db.session.get(Envelope, int(envelope_id)) if envelope_id and envelope_id.isdigit() else None
    require(not envelope_id or envelope is not None, 'validation', 'Sobre inválido.', 422)
    perm = 'envelope.register' if envelope else 'document.upload'
    assignment = find_assignment(current_user, perm, case.area_id)
    require(assignment is not None, 'forbidden', 'Tu perfil no puede incorporar documentos de este tipo.', 403)
    external = request.form.get('external_reference')
    if external and not request.files.get('file'):
        doc, ver = create_document(case, current_user, None, '', request.form.get('kind', 'constancia'), request.form.get('title', ''), request.form.get('classification', 'internal'),
                                   envelope, external[:300], assignment)
    else:
        content, name = _form_file()
        doc, ver = create_document(case, current_user, content, name, request.form.get('kind', 'otro'), request.form.get('title', ''),
                                   request.form.get('classification', 'internal'), envelope, None, assignment)
    db.session.commit()
    doc = db.session.get(Document, doc.id)
    return jsonify(_doc_json(doc, current_user, case, active_assignments(current_user))), 201


@bp.post('/documents/<int:doc_id>/versions')
@auth_required
def new_version(doc_id):
    rate_limit('upload', 30)
    doc = db.session.get(Document, doc_id)
    case = db.session.get(ProcurementCase, doc.case_id) if doc else None
    if not doc or not can_see_metadata(current_user, doc, case):
        raise ApiError('not_found', 'Documento no encontrado.', 404)
    require(not doc.envelope_id, 'immutable', 'Los originales presentados en un sobre no se sobrescriben ni se versionan.', 409)
    assignment = find_assignment(current_user, 'document.upload', case.area_id)
    require(assignment is not None, 'forbidden', 'Tu perfil no puede incorporar documentos.', 403)
    content, name = _form_file()
    ver = store_version(doc, content, name, current_user, assignment, case)
    audit.record(current_user, 'document.version', 'document', doc.id, case=case, reference=ver.sha256[:16],
                 details={'version': ver.version, 'sha256': ver.sha256, 'size': ver.size}, role_code=assignment.role_code, assignment_id=assignment.id)
    db.session.commit()
    return jsonify(_doc_json(db.session.get(Document, doc_id), current_user, case, active_assignments(current_user))), 201


@bp.get('/documents/<int:doc_id>/versions/<int:version>/download')
@auth_required
def download(doc_id, version):
    doc = db.session.get(Document, doc_id)
    case = db.session.get(ProcurementCase, doc.case_id) if doc else None
    if not doc or not can_see_metadata(current_user, doc, case) or not can_read_content(current_user, doc, case):
        raise ApiError('not_found', 'Documento no disponible.', 404)  # no distingue inexistente de reservado
    ver = db.session.scalar(db.select(DocumentVersion).where(DocumentVersion.document_id == doc.id, DocumentVersion.version == version))
    require(ver is not None, 'not_found', 'Versión inexistente.', 404)
    content = get_document_storage().read(ver.storage_key)
    audit.record(current_user, 'document.download', 'document', doc.id, case=case, reference=ver.sha256[:16], details={'version': version})
    db.session.commit()
    name = ver.original_name.encode('ascii', 'ignore').decode() or 'documento'
    resp = Response(content, mimetype=ver.mime)
    resp.headers['Content-Disposition'] = f'attachment; filename="{name}"; filename*=UTF-8\'\'{__import__("urllib.parse").parse.quote(ver.original_name)}'
    resp.headers['Content-Security-Policy'] = "sandbox; default-src 'none'"
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Cache-Control'] = 'private, no-store'
    return resp
