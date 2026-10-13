"""Configuración del backend: las variables de proceso prevalecen sobre un `.env` local opcional."""
import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv


def flag(name, default='false'):
    return os.getenv(name, default).strip().lower() in ('true', '1', 'yes')


def settings():
    root = Path(__file__).resolve().parents[2]
    # load_dotenv no sobreescribe variables ya presentes en el entorno (precedencia: entorno > archivo).
    load_dotenv(root / 'backend' / '.env')
    load_dotenv(root / '.env')
    uri = os.getenv('DATABASE_URI') or os.getenv('DATABASE_URL')
    max_mb = int(os.getenv('MAX_UPLOAD_MB', '10'))
    return dict(
        APP_ENV=os.getenv('APP_ENV', 'production'),
        SECRET_KEY=os.getenv('SECRET_KEY'),
        SQLALCHEMY_DATABASE_URI=uri,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={'pool_pre_ping': True, 'pool_recycle': 280, 'isolation_level': 'READ COMMITTED'},
        PUBLIC_ORIGIN=os.getenv('PUBLIC_ORIGIN', '').rstrip('/'),
        TIMEZONE=os.getenv('TIMEZONE', 'America/Montevideo'),
        COOKIE_SECURE=flag('COOKIE_SECURE'),
        SESSION_COOKIE_SECURE=flag('COOKIE_SECURE'),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_NAME='cc_session',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=float(os.getenv('SESSION_HOURS', '8'))),
        MAX_UPLOAD_MB=max_mb,
        MAX_CONTENT_LENGTH=(max_mb + 1) * 1024 * 1024,
        AUTH_2FA_REQUIRED=flag('AUTH_2FA_REQUIRED', 'true'),
        LOGIN_CAPTCHA=flag('LOGIN_CAPTCHA', 'true'),
        ALLOW_DEMO_SEED=flag('ALLOW_DEMO_SEED'),
        DOCUMENT_STORAGE=os.getenv('DOCUMENT_STORAGE', 'local'),
        DOCUMENT_ROOT=os.getenv('DOCUMENT_ROOT', str(root / 'private-data' / 'documents')),
        MINIO_ENDPOINT=os.getenv('MINIO_ENDPOINT'), MINIO_ACCESS_KEY=os.getenv('MINIO_ACCESS_KEY'),
        MINIO_SECRET_KEY=os.getenv('MINIO_SECRET_KEY'), MINIO_SECURE=flag('MINIO_SECURE'),
        MINIO_BUCKET_NAME=os.getenv('MINIO_BUCKET_NAME'),
        MAIL_SERVER=os.getenv('MAIL_SERVER', 'localhost'), MAIL_PORT=int(os.getenv('MAIL_PORT', '25')),
        MAIL_USE_TLS=flag('MAIL_USE_TLS'), MAIL_USE_SSL=flag('MAIL_USE_SSL'),
        MAIL_USERNAME=os.getenv('MAIL_USERNAME') or None, MAIL_PASSWORD=os.getenv('MAIL_PASSWORD') or None,
        MAIL_DEFAULT_SENDER=os.getenv('MAIL_DEFAULT_SENDER', 'no-reply@compra-clara.invalid'),
        MAIL_SUPPRESS_SEND=flag('MAIL_SUPPRESS_SEND'), MAIL_TIMEOUT=10,
        # IA (nombres de variable heredados de sample/backend y sample/rag-chat; ver docs/IA.md)
        AI_ENABLED=flag('AI_ENABLED'),
        OLLAMA_HOST=os.getenv('OLLAMA_HOST', 'https://ollama.com').rstrip('/'),
        OLLAMA_API_KEY=os.getenv('OLLAMA_API_KEY', ''),
        OLLAMA_MODEL=os.getenv('OLLAMA_MODEL', '').strip(),
        AI_EGRESS_POLICY=os.getenv('AI_EGRESS_POLICY', 'minimized'),
        AI_EGRESS_CLASSES=[c.strip() for c in os.getenv('AI_EGRESS_CLASSES', 'public,internal').split(',') if c.strip()],
        AI_MAX_CONTEXT_CHARS=int(os.getenv('AI_MAX_CONTEXT_CHARS', '24000')),
        AI_TIMEOUT_SECONDS=float(os.getenv('AI_TIMEOUT_SECONDS', '60')),
        AI_MAX_CONCURRENCY=int(os.getenv('AI_MAX_CONCURRENCY', '2')),
        AI_MAX_RETRIES=int(os.getenv('AI_MAX_RETRIES', '1')),
        AI_TOP_K=int(os.getenv('AI_TOP_K', '8')),
        EMBED_MODEL=os.getenv('EMBED_MODEL', 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'),
        EMBEDDER=os.getenv('EMBEDDER', 'fastembed'),
        MODEL_CACHE=os.getenv('MODEL_CACHE', str(root / 'backend' / '.model_cache')),
        TRUST_PROXY=flag('TRUST_PROXY'),
        TRUSTED_PROXY_HOPS=int(os.getenv('TRUSTED_PROXY_HOPS', '1')),
    )
