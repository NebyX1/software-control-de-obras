"""Worker de tareas persistentes (ingesta documental y extracción asistida). Un proceso aparte con la misma imagen del backend."""
import logging
import os
import signal
import time
import uuid
from app import create_app
from app.extensions import db
from app.infrastructure import tasks
from app.infrastructure.models import BackgroundTask

log = logging.getLogger('worker')
STOP = False


def _stop(*_):
    global STOP
    STOP = True


def handle(task):
    if task.kind == 'document_ingest':
        from app.ai.rag.ingest import ingest_document_version
        return ingest_document_version(task.payload['document_version_id'])
    if task.kind == 'ai_extract':
        from app.ai import extraction
        return extraction.run(task.id)
    raise ValueError(f'Tipo de tarea desconocido: {task.kind}')


def run_once(worker_id):
    task_id = tasks.claim(worker_id)
    if task_id is None:
        return False
    task = db.session.get(BackgroundTask, task_id)
    try:
        result = handle(task)
        tasks.succeed(task_id, result)
        log.info('task_ok id=%s kind=%s status=%s', task_id, task.kind, (result or {}).get('status'))
    except Exception as exc:  # el error se redacta: sin contenido de documentos ni secretos
        db.session.rollback()
        tasks.fail(task_id, f'{type(exc).__name__}')
        log.warning('task_failed id=%s kind=%s type=%s', task_id, task.kind, type(exc).__name__)
    return True


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    app = create_app()
    worker_id = f'{os.uname().nodename if hasattr(os, "uname") else "worker"}-{uuid.uuid4().hex[:6]}'
    log.info('worker_start id=%s', worker_id)
    with app.app_context():
        while not STOP:
            try:
                busy = run_once(worker_id)
            except Exception as exc:
                db.session.rollback()
                log.warning('worker_loop_error type=%s', type(exc).__name__)
                busy = False
            if not busy:
                time.sleep(2)
        log.info('worker_stop')


if __name__ == '__main__':
    main()
