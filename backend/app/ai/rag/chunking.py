"""Segmentación por páginas, con el tamaño objetivo del boilerplate rag-chat (≈900 caracteres, máx. 1400)."""
import re

CHUNK_TARGET = 900
CHUNK_MAX = 1400


def split_text(text):
    units = []
    for para in re.split(r'\n+', text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= CHUNK_MAX:
            units.append(para)
        else:
            units.extend(s for s in re.split(r'(?<=[.!?])\s+', para) if s)
    chunks, cur = [], ''
    for u in units:
        while len(u) > CHUNK_MAX:  # párrafo sin puntuación
            if cur:
                chunks.append(cur)
                cur = ''
            chunks.append(u[:CHUNK_MAX])
            u = u[CHUNK_MAX:]
        if cur and len(cur) + len(u) > CHUNK_TARGET:
            chunks.append(cur)
            cur = ''
        cur = f'{cur}\n{u}' if cur else u
    if cur:
        chunks.append(cur)
    return chunks


def chunk_pages(pages):
    """pages: [{'page': n, 'text': str}] → [{'page_from','page_to','text'}]. Un fragmento nunca mezcla páginas (evidencia precisa)."""
    out = []
    for p in pages:
        for part in split_text(p['text']):
            out.append({'page_from': p['page'], 'page_to': p['page'], 'text': part})
    return out
