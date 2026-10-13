"""Embeddings: fastembed (modelo del boilerplate rag-chat, ONNX/CPU) o un embebedor determinista para pruebas unitarias."""
import hashlib
import re
import threading
import numpy as np
from flask import current_app

_lock = threading.Lock()
_models = {}
DIM_HASH = 256


def _normalize(v):
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    n[n == 0] = 1
    return (v / n).astype(np.float32)


def _hash_embed(texts):
    out = np.zeros((len(texts), DIM_HASH), dtype=np.float32)
    for i, t in enumerate(texts):
        words = re.findall(r'\w+', t.lower())
        for w in words:
            for gram in {w[j:j + 3] for j in range(max(1, len(w) - 2))}:
                h = int(hashlib.md5(gram.encode()).hexdigest()[:8], 16)
                out[i, h % DIM_HASH] += 1 if (h >> 8) & 1 else -1
    return _normalize(out)


def embed(texts):
    """Devuelve una matriz float32 normalizada (n, d)."""
    texts = list(texts)
    if not texts:
        return np.zeros((0, DIM_HASH), dtype=np.float32)
    if current_app.config.get('EMBEDDER') == 'hash':
        return _hash_embed(texts)
    name, cache = current_app.config['EMBED_MODEL'], current_app.config['MODEL_CACHE']
    with _lock:
        if name not in _models:
            from fastembed import TextEmbedding
            _models[name] = TextEmbedding(name, cache_dir=cache, threads=2)
        model = _models[name]
    vecs = np.array(list(model.embed(texts, batch_size=16)), dtype=np.float32)
    return _normalize(vecs)


def to_blob(v):
    return np.asarray(v, dtype=np.float32).tobytes()


def from_blob(b):
    return np.frombuffer(b, dtype=np.float32)
