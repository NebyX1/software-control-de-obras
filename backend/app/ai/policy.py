"""Política de envío al proveedor de IA: clasificación, minimización y registro (sin contenido) de cada salida.

Ollama Cloud procesa fuera del servidor los textos que se le envían: la aplicación NO declara que los documentos nunca salen del VPS.
"""
import re
from flask import current_app
from app.extensions import db
from app.infrastructure.models import AiCall
from app.shared.contracts import sha256_hex

EMAIL = re.compile(r'[\w.+-]+@[\w-]+(\.[\w-]+)+')
CI = re.compile(r'\b\d\.?\d{3}\.?\d{3}-?\d\b')
RUT = re.compile(r'\b\d{12}\b')
PHONE = re.compile(r'(?<!\d)(?:\+?598[\s-]?)?0?9\d[\s-]?\d{3}[\s-]?\d{3}(?!\d)')


class EgressBlocked(Exception):
    pass


def policy():
    return current_app.config['AI_EGRESS_POLICY']


def minimize(text):
    """Enmascara correos, teléfonos y documentos de identidad. No altera importes ni cantidades."""
    out = EMAIL.sub('[correo]', text)
    out = RUT.sub('[rut]', out)
    out = CI.sub('[documento]', out)
    out = PHONE.sub('[teléfono]', out)
    return out


def prepare(text, classification):
    """Devuelve (texto a enviar, info). Lanza EgressBlocked si la política o la clasificación lo impiden."""
    pol = policy()
    if pol in ('off', 'metadata_only'):
        raise EgressBlocked(f'La política de envío vigente ({pol}) no permite remitir contenido al proveedor de IA.')
    if classification not in current_app.config['AI_EGRESS_CLASSES']:
        raise EgressBlocked(f'Los documentos clasificados “{classification}” no pueden enviarse al proveedor de IA.')
    limit = current_app.config['AI_MAX_CONTEXT_CHARS']
    out = text if pol == 'full_text' else minimize(text)
    return out[:limit], {'policy': pol, 'classification': classification, 'minimized': pol != 'full_text', 'truncated': len(out) > limit}


def log_call(user, case, kind, status, input_text, model=None, error_code=None, latency_ms=None, response_chars=None, chunk_ids=None, egress=None, prompt_version=None):
    row = AiCall(user_id=user.id if user is not None else None, case_id=case.id if case is not None else None, kind=kind, model=model, prompt_version=prompt_version,
                 input_hash=sha256_hex(input_text or ''), status=status, error_code=error_code, latency_ms=latency_ms, prompt_chars=len(input_text or ''),
                 response_chars=response_chars, chunk_ids=chunk_ids, egress=egress)
    db.session.add(row)
    return row
