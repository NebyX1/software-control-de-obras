"""Custodia de ofertas: ningún canal entrega contenido de sobres cerrados; originales inmutables; apertura solo tras el plazo."""
from tests.flow import Journey, OFFERS


def _until_envelopes(app, api, world):
    j = Journey(app, api, world)
    j.create()
    j.prepare()
    j.open_reception()
    envs = j.receive_offers()
    return j, envs


def _docs(j, role='compras'):
    return j.detail(role)['documents']


def test_sealed_content_unavailable_through_every_channel(app, api, world):
    j, envs = _until_envelopes(app, api, world)
    docs = _docs(j)
    assert docs and all(d['sealed'] and not d['can_download'] for d in docs)
    for role in ('compras', 'tecnica', 'comision', 'control', 'ordenador', 'auditor', 'recepcion', 'administrador', 'contaduria'):
        for d in docs:
            r = api[role].get(f'/api/v1/documents/{d["id"]}/versions/1/download')
            assert r.status_code == 404, (role, r.status_code)
        det = api[role].get(f'/api/v1/cases/{j.code}')
        if det.status_code == 200:
            body = det.get_json()
            assert body['offers'] == [] and body['evaluation'] is None
    detail = j.detail()
    assert detail['offers_sealed'] is True
    # el contenido tampoco aparece en el detalle serializado
    assert 'Garantía 36 meses' not in str(detail)
    # no se extrajo texto, no hay tareas de ingesta ni fragmentos recuperables
    from app.extensions import db
    from app.infrastructure.models import BackgroundTask, DocumentChunk, DocumentVersion
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(DocumentChunk.id)).where(DocumentChunk.case_id == detail['id'])) == 0
        assert db.session.scalar(db.select(db.func.count(BackgroundTask.id)).where(BackgroundTask.case_id == detail['id'], BackgroundTask.kind == 'document_ingest')) == 0
        assert {v.text_status for v in db.session.scalars(db.select(DocumentVersion))
                if v.document.case_id == detail['id']} == {'held_sealed'}
    # la IA tampoco puede leerlos
    r = api['tecnica'].post(f'/api/v1/ai/cases/{j.code}/extract', json={'offer_id': 1, 'document_id': docs[0]['id']})
    assert r.status_code in (404, 503)
    from app.modules.documents.policies import readable_document_ids
    from app.infrastructure.models import User, ProcurementCase
    with app.app_context():
        case = db.session.scalar(db.select(ProcurementCase).where(ProcurementCase.code == j.code))
        for role, uid in world['users'].items():
            assert readable_document_ids(db.session.get(User, uid), case) == [], role


def test_unauthorized_channel_not_registered(app, api, world):
    j = Journey(app, api, world)
    j.create()
    j.prepare()
    j.open_reception()
    s = j.supplier('Canal')
    r = j.act('recepcion', 'envelope.register', {'supplier_id': s['id'], 'channel': 'correo_pliego', 'custody_note': 'Llegó por correo personal'}, expect=422)
    assert r['code'] == 'channel_not_authorized'


def test_opening_blocked_before_deadline_with_clear_reason(app, api, world):
    j, _ = _until_envelopes(app, api, world)
    r = j.act('compras', 'opening.perform', {'reference': 'ACTA', 'participants': 'A'}, expect=422)
    assert 'antes del vencimiento' in r['message']


def test_late_envelope_recorded_but_never_opened(app, api, world):
    j = Journey(app, api, world)
    j.create()
    j.prepare()
    j.open_reception()
    s_ok, s_late = j.supplier('EnPlazo'), j.supplier('Tarde')
    j.act('recepcion', 'envelope.register', {'supplier_id': s_ok['id'], 'channel': 'presencial', 'custody_note': 'Recibido en plazo, custodia en caja.'})
    j.expire_deadline()
    j.act('recepcion', 'envelope.register', {'supplier_id': s_late['id'], 'channel': 'presencial', 'custody_note': 'Llegó después del vencimiento.'})
    envs = j.detail('recepcion')['envelopes']
    assert {e['status'] for e in envs} == {'received', 'late'}
    j.act('compras', 'opening.perform', {'reference': 'ACTA-L', 'participants': 'Compras\nRecepción'})
    d = j.detail()
    assert len(d['offers']) == 1 and d['offers'][0]['supplier'].startswith('EnPlazo')


def test_deadline_extension_is_recorded_and_communicated(app, api, world):
    j, _ = _until_envelopes(app, api, world)
    j.act('compras', 'deadline.extend', {'new_deadline': '2030-01-01T10:00:00-03:00', 'communicated_ref': 'COM-UNIF-1', 'reason': 'Se amplía la consulta a todos los interesados.'})
    rec = j.detail()['reception']
    assert rec['extensions'][0]['communicated_ref'] == 'COM-UNIF-1' and rec['timezone'] == 'America/Montevideo'
    j.act('compras', 'deadline.extend', {'new_deadline': '2029-01-01T10:00:00-03:00', 'communicated_ref': 'X', 'reason': 'Intento de acortar'}, expect=422)


def test_after_opening_content_is_readable_by_permitted_roles_only(app, api, world):
    j, _ = _until_envelopes(app, api, world)
    j.open()
    docs = _docs(j, 'compras')
    assert all(not d['sealed'] and d['can_download'] for d in docs)
    d = docs[0]
    r = api['tecnica'].get(f'/api/v1/documents/{d["id"]}/versions/1/download')
    assert r.status_code == 200 and r.headers['X-Content-Type-Options'] == 'nosniff' and 'attachment' in r.headers['Content-Disposition']
    assert api['solicitante'].get(f'/api/v1/documents/{d["id"]}/versions/1/download').status_code == 404  # sin offer.read
    assert api['solicitante2'].get(f'/api/v1/documents/{d["id"]}/versions/1/download').status_code == 404  # otra área


def test_envelope_originals_are_immutable(app, api, world):
    j, _ = _until_envelopes(app, api, world)
    d = _docs(j)[0]
    r = api['compras'].upload(f'/api/v1/documents/{d["id"]}/versions', {}, 'otra.txt', b'reemplazo del original')
    assert r.status_code == 409 and r.get_json()['code'] == 'immutable'
    j.expire_deadline()
    env = j.detail('recepcion')['envelopes'][0]
    r = api['recepcion'].upload(f'/api/v1/cases/{j.code}/documents', {'kind': 'oferta', 'title': 'Tardío', 'envelope_id': str(env['id'])}, 'x.txt', b'documento tardio')
    assert r.status_code == 409 and r.get_json()['code'] == 'deadline_passed'


def test_confidential_annex_separation_after_opening(app, api, world):
    j, envs = _until_envelopes(app, api, world)
    env = envs[0]
    r = api['recepcion'].upload(f'/api/v1/cases/{j.code}/documents', {'kind': 'anexo_confidencial', 'title': 'Anexo confidencial de costos', 'envelope_id': str(env['id'])},
                                'anexo.txt', b'Estructura de costos reservada del proveedor.')
    assert r.status_code == 201
    j.open()
    anexo = next(d for d in _docs(j, 'compras') if d['title'].startswith('Anexo'))
    assert anexo['classification'] == 'confidential'
    assert api['compras'].get(f'/api/v1/documents/{anexo["id"]}/versions/1/download').status_code == 200
    assert api['tecnica'].get(f'/api/v1/documents/{anexo["id"]}/versions/1/download').status_code == 404
    from app.extensions import db
    from app.infrastructure.models import DocumentChunk
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(DocumentChunk.id)).where(DocumentChunk.document_id == anexo['id'])) == 0
