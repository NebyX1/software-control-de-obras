"""Carga de documentos: tipo real, nombre, tamaño, contenido activo, versiones, hash y descarga segura."""
import hashlib
import io
from tests.flow import Journey


def _case(app, api, world):
    j = Journey(app, api, world)
    j.create()
    return j


def up(api, j, name, content, kind='otro', title='Documento de prueba', role='compras', cls='internal', mimetype='application/octet-stream'):
    return api[role].upload(f'/api/v1/cases/{j.code}/documents', {'kind': kind, 'title': title, 'classification': cls}, name, content, mimetype)


def blank_pdf():
    from pypdf import PdfWriter
    buf = io.BytesIO()
    w = PdfWriter()
    w.add_blank_page(200, 200)
    w.write(buf)
    return buf.getvalue()


def minimal_pdf(extra=b''):
    return b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n' + extra + b'trailer<</Root 1 0 R/Size 4>>\n%%EOF'


def test_valid_text_and_hash_of_original(app, api, world):
    j = _case(app, api, world)
    content = 'Informe técnico con acentos: ñandú, garantía 36 meses.'.encode()
    r = up(api, j, 'informe.txt', content, kind='constancia')
    assert r.status_code == 201, r.get_json()
    v = r.get_json()['versions'][0]
    assert v['sha256'] == hashlib.sha256(content).hexdigest() and v['mime'] == 'text/plain' and v['size'] == len(content)
    dl = api['compras'].get(f'/api/v1/documents/{r.get_json()["id"]}/versions/1/download')
    assert dl.status_code == 200 and dl.data == content
    assert dl.headers['Content-Security-Policy'].startswith('sandbox') and dl.headers['Cache-Control'] == 'private, no-store'


def test_executables_and_archives_rejected_even_with_safe_extension(app, api, world):
    j = _case(app, api, world)
    for name, content in (('virus.pdf', b'MZ\x90\x00\x03\x00\x00\x00' + b'\x00' * 100), ('script.txt', b'#!/bin/sh\nrm -rf /'), ('doc.txt', b'PK\x03\x04' + b'\x00' * 50), ('elf.png', b'\x7fELF' + b'\x00' * 50)):
        r = up(api, j, name, content)
        assert r.status_code == 422, (name, r.get_json())


def test_extension_must_match_real_content(app, api, world):
    j = _case(app, api, world)
    assert up(api, j, 'texto.pdf', b'esto es texto plano, no un pdf').status_code == 422
    assert up(api, j, 'foto.png', minimal_pdf()).status_code == 422


def test_active_pdf_content_rejected(app, api, world):
    j = _case(app, api, world)
    for marker in (b'/JavaScript', b'/OpenAction', b'/Launch', b'/EmbeddedFile'):
        r = up(api, j, 'activo.pdf', minimal_pdf(b'4 0 obj<<' + marker + b' 5 0 R>>endobj\n'))
        assert r.status_code == 422, marker
        assert r.get_json()['code'] == 'active_pdf'


def test_valid_pdf_and_png_accepted(app, api, world):
    j = _case(app, api, world)
    assert up(api, j, 'ok.pdf', blank_pdf()).status_code == 201
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), 'white').save(buf, 'PNG')
    r = up(api, j, 'ok.png', buf.getvalue())
    assert r.status_code == 201 and r.get_json()['versions'][0]['text_status'] == 'no_text'  # sin OCR: pendiente, no simulado


def test_oversize_rejected(app, api, world):
    j = _case(app, api, world)
    r = up(api, j, 'grande.txt', b'a' * (11 * 1024 * 1024))
    assert r.status_code in (413, 422)


def test_filename_is_never_used_as_path(app, api, world):
    j = _case(app, api, world)
    r = up(api, j, '../../etc/passwd.txt', b'contenido inocuo de prueba')
    assert r.status_code == 201
    v = r.get_json()['versions'][0]
    assert '/' not in v['original_name'] and '\\' not in v['original_name']
    import os
    for root, _, files in os.walk(app.config['DOCUMENT_ROOT']):
        assert all(len(f) == 32 for f in files if not f.endswith('.tmp'))  # claves opacas generadas por el servidor


def test_new_version_keeps_previous_original(app, api, world):
    j = _case(app, api, world)
    doc = up(api, j, 'a.txt', b'version uno del documento').get_json()
    r = api['compras'].upload(f'/api/v1/documents/{doc["id"]}/versions', {}, 'a.txt', b'version dos del documento')
    assert r.status_code == 201 and [v['version'] for v in r.get_json()['versions']] == [1, 2]
    assert api['compras'].get(f'/api/v1/documents/{doc["id"]}/versions/1/download').data == b'version uno del documento'


def test_permissions_on_upload(app, api, world):
    j = _case(app, api, world)
    assert up(api, j, 'x.txt', b'contenido de prueba', role='solicitante2').status_code == 404  # otra área
    assert up(api, j, 'x.txt', b'contenido de prueba', role='administrador').status_code == 404
    assert up(api, j, 'x.txt', b'contenido de prueba', role='auditor').status_code == 403


def test_external_reference_is_distinct_from_a_file(app, api, world):
    j = _case(app, api, world)
    r = api['compras'].client.post(f'/api/v1/cases/{j.code}/documents', data={'kind': 'constancia', 'title': 'Constancia ARCE externa', 'external_reference': 'https://www.gub.uy/ejemplo'},
                                   headers={'X-CSRF-Token': api['compras'].csrf})
    assert r.status_code == 201
    d = r.get_json()
    assert d['external_reference'] and d['versions'] == []
