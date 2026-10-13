"""Cola persistente de tareas con lease (patrón de `receipts/service.py` del boilerplate, generalizado).

Una tarea sobrevive reinicios: si el worker muere, el lease vence y otra instancia la retoma. Los reintentos están
acotados (`max_attempts`) y con espera creciente; agotados, la tarea queda en `dead` con un error redactado.
"""
from datetime import timedelta
from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.infrastructure.models import BackgroundTask
from app.shared.contracts import utcnow

LEASE_SECONDS = 180


def enqueue(kind, payload, case_id=None, user_id=None, dedupe_key=None, max_attempts=3):
    if dedupe_key:
        existing = db.session.scalar(db.select(BackgroundTask).where(BackgroundTask.dedupe_key == dedupe_key))
        if existing:
            return existing
    task = BackgroundTask(kind=kind, payload=payload, case_id=case_id, created_by=user_id, dedupe_key=dedupe_key,
                          max_attempts=max_attempts, run_after=utcnow())
    db.session.add(task)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise
    return task


def claim(worker_id, kinds=None):
    """Toma una tarea lista (o con lease vencido). Devuelve su id o None."""
    now = utcnow()
    q = (db.select(BackgroundTask)
         .where(or_(BackgroundTask.status == 'queued', (BackgroundTask.status == 'running') & (BackgroundTask.lease_until < now)),
                BackgroundTask.run_after <= now)
         .order_by(BackgroundTask.id).limit(1).with_for_update(skip_locked=True))
    if kinds:
        q = q.where(BackgroundTask.kind.in_(kinds))
    task = db.session.scalar(q)
    if not task:
        db.session.rollback()
        return None
    if task.attempts >= task.max_attempts:
        task.status, task.last_error, task.finished_at = 'dead', task.last_error or 'Reintentos agotados.', now
        db.session.commit()
        return None
    task.status, task.attempts, task.lease_owner = 'running', task.attempts + 1, worker_id
    task.lease_until, task.started_at = now + timedelta(seconds=LEASE_SECONDS), now
    db.session.commit()
    return task.id


def succeed(task_id, result=None):
    task = db.session.get(BackgroundTask, task_id, populate_existing=True)
    task.status, task.result, task.finished_at, task.lease_owner, task.lease_until, task.last_error = 'succeeded', result, utcnow(), None, None, None
    db.session.commit()


def fail(task_id, error, retry=True):
    task = db.session.get(BackgroundTask, task_id, populate_existing=True)
    msg = str(error)[:290]
    task.lease_owner, task.lease_until, task.last_error = None, None, msg
    if retry and task.attempts < task.max_attempts:
        task.status = 'queued'
        task.run_after = utcnow() + timedelta(seconds=min(300, 10 * 2 ** task.attempts))
    else:
        task.status, task.finished_at = ('dead' if retry else 'failed'), utcnow()
    db.session.commit()
