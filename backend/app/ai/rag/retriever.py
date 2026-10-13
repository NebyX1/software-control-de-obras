"""Recuperación híbrida (densa + BM25 con fusión RRF), como en `sample/rag-chat/rag.py`, pero sobre el subconjunto AUTORIZADO.

La autorización se aplica ANTES de recuperar: solo se cargan fragmentos activos de documentos que el usuario puede leer ahora.
Al retirar un permiso o un documento, el fragmento deja de recuperarse de inmediato (estado y política se consultan en cada búsqueda).
"""
import re
import numpy as np
from app.extensions import db
from app.infrastructure.models import DocumentChunk
from app.ai.rag.embedder import embed, from_blob
from app.ai.rag.lexical import BM25, tokenize

DENSE_MIN = 0.15
RRF_K = 60

EXPANSIONS = {
    r'\b(adjudic\w*|ordenador)\b': 'adjudicación ordenador dictamen motivación apartamiento',
    r'\b(umbral|tope|monto|l[ií]mite)\b': 'montos topes 2026 compra directa concurso licitación abreviada',
    r'\b(garant[ií]a)\b': 'garantía mantenimiento de oferta fiel cumplimiento',
    r'\b(sobre|apertura|oferta)\b': 'apertura de sobres recepción ofertas acta reserva',
}


def expand(query):
    extra = [v for pat, v in EXPANSIONS.items() if re.search(pat, query.lower())]
    return f'{query} {" ".join(extra)}' if extra else query


def search(query, corpus, case_id=None, document_ids=None, k=8):
    q = db.select(DocumentChunk).where(DocumentChunk.status == 'active', DocumentChunk.corpus == corpus)
    if corpus == 'case':
        if not document_ids:
            return []
        q = q.where(DocumentChunk.case_id == case_id, DocumentChunk.document_id.in_(document_ids))
    chunks = [c for c in db.session.scalars(q.order_by(DocumentChunk.id)).all() if c.embedding]
    if not chunks:
        return []
    qv = embed([expand(query)])[0]
    rows = [(c, from_blob(c.embedding)) for c in chunks]
    rows = [(c, v) for c, v in rows if v.shape == qv.shape]
    if not rows:
        return []
    matrix = np.vstack([v for _, v in rows])
    dense = matrix @ qv
    bm = BM25([tokenize(f'{c.section or ""} {c.label or ""} {c.text}') for c, _ in rows])
    sparse = bm.scores(tokenize(query))
    d_rank = [(int(i), float(dense[i])) for i in np.argsort(-dense)[:20] if sparse[i] > 0 or dense[i] > DENSE_MIN]
    s_rank = [(int(i), float(sparse[i])) for i in np.argsort(-sparse)[:20] if sparse[i] > 0]
    fused = {}
    for ranking in (d_rank, s_rank):
        for rank, (i, _) in enumerate(ranking):
            fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + rank)
    top = sorted(fused, key=fused.get, reverse=True)[:k]
    return [{'chunk': rows[i][0], 'score': float(dense[i]), 'rrf': fused[i]} for i in top]
