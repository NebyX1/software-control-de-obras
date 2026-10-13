"""Estados internos del expediente y su correspondencia con las ocho etapas visibles.

`stage` y `status` los gestiona el servidor; el navegador nunca envía un entero de etapa.
"""
STAGES = ['Solicitud', 'Preparación', 'Ofertas', 'Evaluación', 'Decisión', 'Orden y entrega', 'Factura y pago', 'Cierre']

STATUS_STAGE = {
    'draft': 0, 'submitted': 0, 'preparation': 1, 'receiving_offers': 2, 'offers_opened': 2, 'evaluation': 3, 'decision': 4,
    'awarded': 5, 'ordered': 5, 'invoicing': 6, 'closed': 7,
}
BRANCH_STATUSES = {'cancelled', 'deserted', 'offers_rejected', 'exception_review'}
TERMINAL = {'closed', 'cancelled'}
ACTIVE = set(STATUS_STAGE) - {'closed'}

STATUS_LABEL = {
    'draft': 'Borrador', 'submitted': 'Para recibir', 'preparation': 'En preparación', 'receiving_offers': 'Recibiendo ofertas',
    'offers_opened': 'Ofertas abiertas', 'evaluation': 'En evaluación', 'decision': 'En decisión y control',
    'awarded': 'Adjudicada', 'ordered': 'Orden emitida', 'invoicing': 'Factura y pago', 'closed': 'Completada',
    'cancelled': 'Cancelada', 'deserted': 'Desierta', 'offers_rejected': 'Ofertas rechazadas', 'exception_review': 'Revisión de excepción',
}
# Tono visual del estado (clases del sistema visual Compra Clara)
STATUS_TONE = {
    'draft': 'neutral', 'submitted': 'blue', 'preparation': 'amber', 'receiving_offers': 'blue', 'offers_opened': 'purple',
    'evaluation': 'purple', 'decision': 'amber', 'awarded': 'blue', 'ordered': 'blue', 'invoicing': 'amber', 'closed': 'green',
    'cancelled': 'red', 'deserted': 'red', 'offers_rejected': 'red', 'exception_review': 'amber',
}

# Orden en que se sugiere la acción principal por estado (la primera no satisfecha y sin bloqueos).
NEXT_BY_STATUS = {
    'draft': ['request.submit'],
    'submitted': ['request.receive'],
    'preparation': ['procedure.classify', 'availability.register', 'spec.approve', 'call.authorize', 'publicity.register', 'framework.select'],
    'receiving_offers': ['envelope.register', 'opening.perform'],
    'offers_opened': ['offer.record', 'requirement.review', 'evaluation.run'],
    'evaluation': ['evaluation.run', 'evaluation.send'],
    'decision': ['opinion.register', 'control.register', 'control.respond', 'award.register'],
    'awarded': ['communication.register', 'contract.register', 'order.issue'],
    'ordered': ['receipt.register', 'invoice.register'],
    'invoicing': ['invoice.conform', 'payment.control', 'payment.authorize', 'payment.record', 'receipt.register', 'invoice.register', 'case.close'],
    'closed': [],
    'cancelled': [], 'deserted': ['exception.request', 'procedure.restart'], 'offers_rejected': ['exception.request', 'procedure.restart'],
    'exception_review': ['exception.resolve', 'procedure.restart'],
}
