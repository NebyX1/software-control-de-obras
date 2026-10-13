"""Indexa el corpus normativo con ámbito, vigencia y estado de validación. El informe se rotula como documento de diseño."""
import json
from pathlib import Path
from app.extensions import db
from app.infrastructure.models import DocumentChunk, NormativeSource
from app.ai.rag.chunking import chunk_pages
from app.ai.rag.embedder import embed, to_blob

DATA = Path(__file__).resolve().parents[3] / 'data'


def index_normative():
    for old in db.session.scalars(db.select(DocumentChunk).where(DocumentChunk.corpus == 'normative')):
        db.session.delete(old)
    db.session.flush()
    rows, texts = [], []
    for s in db.session.scalars(db.select(NormativeSource).order_by(NormativeSource.code)):
        text = (f'{s.code} · {s.titulo} ({s.organismo}). {s.hallazgo} Fuente: {s.url}. Consultada el {s.consulta.isoformat()}. '
                f'Tipo: {s.kind}. Estado de validación: {s.validation_status}.')
        rows.append(dict(label=f'{s.code} {s.titulo}', normative_source_id=s.id, section=s.code, text=text, scope=s.scope,
                         validity=f'Consultada {s.consulta.isoformat()}; sin validación jurídica institucional'))
        texts.append(f'{s.titulo}\n{s.hallazgo}')
    informe = json.loads((DATA / 'informe_diseno.json').read_text(encoding='utf-8'))
    for c in chunk_pages(informe['pages']):
        rows.append(dict(label=f'Informe de diseño, p. {c["page_from"]}', normative_source_id=None, section='informe_diseno',
                         text=c['text'], scope='Propuesta de diseño (no es una norma)', validity='Informe v1.0, 12/10/2026',
                         page_from=c['page_from'], page_to=c['page_to']))
        texts.append(c['text'])
    vecs = embed(texts)
    for i, (r, v) in enumerate(zip(rows, vecs)):
        db.session.add(DocumentChunk(corpus='normative', seq=i, embedding=to_blob(v), classification='public', status='active', **r))
    db.session.commit()
    return f'Indexados {len(rows)} fragmentos normativos.'
