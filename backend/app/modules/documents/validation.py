"""Validación y lectura de archivos en un subproceso con límite de tiempo (patrón de `sample/backend/.../validation.py`).

El contenido y el nombre son datos no confiables. Solo se aceptan PDF sin cifrar ni contenido activo, PNG/JPEG con límite
de píxeles y texto plano UTF-8. Nunca se abre una ruta suministrada por el usuario.
"""
import json
import os
import re
import subprocess
import sys
import unicodedata
from io import BytesIO
from pathlib import Path
from app.shared.errors import ApiError, require

MAX_PAGES = 300
MAX_TEXT_CHARS = 2_000_000
IMAGE_PIXELS = 20_000_000
EXT_BY_MIME = {'application/pdf': {'.pdf'}, 'image/png': {'.png'}, 'image/jpeg': {'.jpg', '.jpeg'}, 'text/plain': {'.txt'}}
ACTIVE_PDF_MARKERS = (b'/JavaScript', b'/JS ', b'/JS(', b'/JS<', b'/Launch', b'/EmbeddedFile', b'/OpenAction', b'/AA ', b'/AA<', b'/RichMedia', b'/XFA')


def safe_filename(name):
    """Nombre solo para mostrar: sin rutas, sin caracteres de control y acotado."""
    name = unicodedata.normalize('NFC', str(name or 'archivo')).replace('\\', '/').split('/')[-1]
    name = ''.join(c for c in name if c.isprintable() and c not in '<>:"|?*')
    name = re.sub(r'\s+', ' ', name).strip(' .') or 'archivo'
    return name[:200]


def _sniff(content):
    if content.startswith(b'%PDF-'):
        return 'application/pdf'
    if content.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if content.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if content[:2] in (b'MZ', b'#!') or content[:4] == b'\x7fELF' or content[:2] == b'PK':
        raise ApiError('file_type', 'No se admiten ejecutables ni archivos comprimidos. Usá PDF, JPG, PNG o TXT.', 422)
    try:
        text = content.decode('utf-8')
    except UnicodeDecodeError:
        raise ApiError('file_type', 'Tipo de archivo no admitido. Usá PDF, JPG, PNG o TXT (UTF-8).', 422)
    if '\x00' in text:
        raise ApiError('file_type', 'Tipo de archivo no admitido.', 422)
    return 'text/plain'


def inspect(content, extract_text=False, max_size=10 * 1024 * 1024):
    """Valida estructura y, opcionalmente, extrae texto por página. Se ejecuta dentro del subproceso."""
    if not 0 < len(content) <= max_size:
        raise ApiError('file_size', f'El archivo debe tener contenido y no superar {max_size // (1024 * 1024)} MB.', 413)
    mime = _sniff(content)
    pages = []
    if mime == 'application/pdf':
        from pypdf import PdfReader
        for marker in ACTIVE_PDF_MARKERS:
            require(marker not in content, 'active_pdf', 'El PDF contiene acciones o contenido activo; exportá una copia sin acciones.', 422)
        reader = PdfReader(BytesIO(content), strict=False)
        require(not reader.is_encrypted, 'encrypted_pdf', 'Subí un PDF sin contraseña.', 422)
        require(0 < len(reader.pages) <= MAX_PAGES, 'pdf_pages', f'El PDF debe tener entre 1 y {MAX_PAGES} páginas.', 422)
        root = reader.trailer['/Root']
        require('/OpenAction' not in root and '/AA' not in root, 'active_pdf', 'El PDF contiene acciones activas.', 422)
        count = len(reader.pages)
        if extract_text:
            total = 0
            for n, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ''
                total += len(text)
                require(total <= MAX_TEXT_CHARS, 'text_limit', 'El texto del documento supera el límite admitido.', 422)
                pages.append({'page': n, 'text': text})
    elif mime in ('image/png', 'image/jpeg'):
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = IMAGE_PIXELS
        with Image.open(BytesIO(content)) as image:
            require(image.format in ('JPEG', 'PNG'), 'file_type', 'Usá PDF, JPG, PNG o TXT.', 422)
            require(image.width * image.height <= IMAGE_PIXELS, 'image_pixels', 'La imagen supera 20 millones de píxeles.', 422)
            image.verify()
        count = 1
    else:
        text = content.decode('utf-8')
        require(len(text) <= MAX_TEXT_CHARS, 'text_limit', 'El texto supera el límite admitido.', 422)
        count = 1
        if extract_text:
            pages.append({'page': 1, 'text': text})
    return {'mime': mime, 'page_count': count, 'pages': pages}


def run_inspect(content, extract_text=False, timeout=5, max_size=10 * 1024 * 1024):
    require(0 < len(content) <= max_size, 'file_size', f'El archivo debe tener contenido y no superar {max_size // (1024 * 1024)} MB.', 413)
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[3])}
    args = [sys.executable, '-m', 'app.modules.documents.validation', '--worker', '1' if extract_text else '0', str(max_size)]
    try:
        result = subprocess.run(args, input=content, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=env)
        payload = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, ValueError):
        raise ApiError('document_processing_limit', 'No se pudo comprobar el archivo dentro del tiempo límite. Exportá una copia más simple.', 422)
    if 'error' in payload:
        raise ApiError(payload['code'], payload['error'], payload['status'])
    return payload


def validate_upload(content, filename, max_size):
    info = run_inspect(content, False, 5, max_size)
    ext = Path(safe_filename(filename)).suffix.lower()
    require(ext in EXT_BY_MIME[info['mime']], 'extension_mismatch',
            'La extensión del archivo no coincide con su contenido real.', 422)
    return info


if __name__ == '__main__':
    try:
        extract = sys.argv[2] == '1'
        limit = int(sys.argv[3])
        print(json.dumps(inspect(sys.stdin.buffer.read(limit + 1), extract, limit)))
    except ApiError as exc:
        print(json.dumps({'error': exc.message, 'code': exc.code, 'status': exc.status}))
    except Exception:
        print(json.dumps({'error': 'No se pudo abrir el archivo. Exportalo de nuevo como PDF, JPG, PNG o TXT.', 'code': 'invalid_file', 'status': 422}))
