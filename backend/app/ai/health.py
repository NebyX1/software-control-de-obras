"""Estado de la asistencia (sin inferencias periódicas): configuración + resultado de las llamadas reales recientes."""
from urllib.parse import urlparse
from flask import current_app
from app.extensions import db
from app.infrastructure.models import AiCall
from app.ai import client


def ai_status():
    cfg = client.config()
    out = {'enabled': cfg['enabled'], 'model': cfg['model'] or None, 'connection': 'direct_cloud' if client.is_direct_cloud(cfg['host']) else 'local_daemon',
           'host': urlparse(cfg['host']).hostname, 'egress_policy': current_app.config['AI_EGRESS_POLICY'], 'state': 'unconfigured',
           'message': 'Asistencia no configurada.'}
    if not cfg['enabled']:
        out.update(state='disabled', message='La asistencia automática está deshabilitada. Los módulos de compras y el cálculo funcionan con normalidad.')
        return out
    if not cfg['model']:
        out['message'] = 'Falta OLLAMA_MODEL.'
        return out
    recent = db.session.scalars(db.select(AiCall).where(AiCall.status.in_(('ok', 'error', 'invalid'))).order_by(AiCall.id.desc()).limit(5)).all()
    out['state'], out['message'] = 'ready', 'Configurada. Aún no hay llamadas reales registradas.'
    if recent:
        last = recent[0]
        out['last_call'] = {'status': last.status, 'error_code': last.error_code, 'at': last.created_at.isoformat() if last.created_at else None}
        if last.status == 'ok':
            out['state'], out['message'] = 'ok', 'La última llamada al proveedor fue exitosa.'
        else:
            out['state'] = 'degraded'
            out['message'] = ('La asistencia está degradada: ' + (client.MESSAGES.get(last.error_code, 'la última llamada falló')) +
                              ' Podés seguir trabajando; los cálculos no dependen de la IA.')
    return out
