"""Adaptadores de integración con estados explícitos. Ninguna integración externa está conectada: no se simula ningún éxito.

Estados: `connected` (verificada), `manual_with_evidence` (registro manual con constancia auténtica por un usuario autorizado),
`not_configured` (requiere habilitación institucional).
"""
from flask import Blueprint, jsonify, current_app
from app.modules.identity.service import perm_required

bp = Blueprint('integrations', __name__, url_prefix='/api/v1/integrations')

ADAPTERS = [
    {'code': 'rupe', 'name': 'RUPE · Registro Único de Proveedores del Estado', 'state': 'manual_with_evidence',
     'detail': 'El estado del proveedor se registra con constancia y vigencia (Proveedores → Estados). No hay consulta automática.', 'requires': 'Acceso autorizado y frecuencia de verificación (informe §17).'},
    {'code': 'sice_arce', 'name': 'SICE / Compras Estatales (ARCE)', 'state': 'manual_with_evidence',
     'detail': 'Publicidad y adjudicación se registran como constancia externa. No existe API pública de escritura verificada.', 'requires': 'Acuerdo y contrato técnico específicos.'},
    {'code': 'sifi', 'name': 'Sistema financiero de la Intendencia (SIFI)', 'state': 'not_configured',
     'detail': 'Crédito, imputación y pago se registran manualmente con respaldo. La aplicación no consulta ni mueve fondos.', 'requires': 'Operaciones permitidas, identificadores y fuente de verdad.'},
    {'code': 'expediente', 'name': 'Expediente institucional / Geoexpedientes', 'state': 'not_configured',
     'detail': 'Las actuaciones auténticas residen en el expediente institucional; aquí se referencian.', 'requires': 'API, permisos, versionado y firma verificados.'},
    {'code': 'firma', 'name': 'Firma electrónica', 'state': 'not_configured', 'detail': 'La aplicación no firma actos; las constancias firmadas se incorporan como documentos.', 'requires': 'Proveedor de firma y política.'},
    {'code': 'dgi', 'name': 'DGI · comprobantes fiscales', 'state': 'not_configured', 'detail': 'No se valida un CFE contra DGI; el duplicado se controla por emisor, tipo, serie y número.', 'requires': 'Servicio y credenciales de DGI.'},
    {'code': 'bancos', 'name': 'Bancos / pagos', 'state': 'not_configured', 'detail': 'El registro de pago con comprobante no prueba una transferencia bancaria. No se envían órdenes.', 'requires': 'Convenio bancario y contrato técnico.'},
    {'code': 'ocds', 'name': 'Datos abiertos OCDS (lectura)', 'state': 'not_configured', 'detail': 'Sirven para consultar información publicada; no sustituyen el expediente ni el canal de ofertas.', 'requires': 'Definir uso analítico.'},
]


@bp.get('')
@perm_required('integration.read')
def status():
    ai = {'code': 'ollama', 'name': 'IA · Ollama (extracción y consulta asistidas)',
          'state': 'configured' if (current_app.config['AI_ENABLED'] and current_app.config['OLLAMA_MODEL']) else 'not_configured',
          'detail': 'Configurada por variables de entorno; el estado de la última llamada real está en /health/ai. La asistencia nunca decide ni modifica actos.',
          'requires': 'Modelo disponible en el endpoint configurado.'}
    return jsonify(items=ADAPTERS + [ai])
