"""Etapas 6 y 7 (Orden y entrega; Factura y pago) y cierre."""
from decimal import Decimal
from app.extensions import db
from app.infrastructure.models import (Award, AwardLine, Communication, Contract, Guarantee, PurchaseOrder, OrderLine, Receipt, ReceiptLine, Invoice,
                                       InvoiceLine, InvoiceStep, Payment, Intervention, ContractModification, CaseClosure, Offer)
from app.modules.procurement import forms as F, inputs as inp
from app.modules.procurement.actions.common import doc_in_case
from app.modules.procurement.framework import action
from app.modules.rules.service import suggest_procedure
from app.shared.contracts import utcnow, dstr, money, display2, canonical_hash
from app.shared.errors import ApiError, require


def active_award(case_id):
    return db.session.scalar(db.select(Award).where(Award.case_id == case_id, Award.status == 'active'))


def order_of(case_id):
    return db.session.scalar(db.select(PurchaseOrder).where(PurchaseOrder.case_id == case_id, PurchaseOrder.status == 'active'))


def locked_order_lines(order_id):
    return {l.id: l for l in db.session.scalars(db.select(OrderLine).where(OrderLine.order_id == order_id).order_by(OrderLine.id)
                                                .with_for_update().execution_options(populate_existing=True))}


# ---------------------------------------------------------------- comunicación, contrato y garantías

@action('communication.register', 'Registrar notificación o publicidad', 'communication.register', {'awarded'},
        form=lambda ctx: [F.field('kind', 'Tipo', 'select', options=F.options([('notificacion', 'Notificación a oferentes'), ('publicacion', 'Publicación de la adjudicación')])),
                          F.field('state', 'Estado', 'select', options=F.options([('pending', 'Pendiente'), ('external_constancia', 'Constancia externa de envío/publicación')]),
                                  help='Este registro no envía comunicaciones ni publica en ARCE. “Confirmada por integración” no está disponible.'),
                          F.field('recipients', 'Destinatarios / medio', required=False), F.field('reference', 'Referencia de la constancia', required=False),
                          F.field('document_id', 'Constancia (documento)', 'document', required=False), F.field('note', 'Observaciones', 'textarea', required=False, rows=2)],
        description='Diferencia pendiente, constancia externa y confirmación por integración. Una llamada a esta API no prueba una publicación oficial.')
def communication_register(ctx, data):
    state = inp.choice(data, 'state', 'Estado', ('pending', 'external_constancia'))
    doc = doc_in_case(ctx, data.get('document_id'))
    c = Communication(case_id=ctx.case.id, award_id=active_award(ctx.case.id).id, kind=inp.choice(data, 'kind', 'Tipo', ('notificacion', 'publicacion')), state=state,
                      recipients=inp.text(data, 'recipients', 'Destinatarios', 2, 300, required=False), reference=inp.text(data, 'reference', 'Referencia', 3, 200, required=state == 'external_constancia'),
                      document_id=doc.id if doc else None, note=inp.text(data, 'note', 'Observaciones', 1, 500, required=False), created_by=ctx.user.id)
    db.session.add(c)
    db.session.flush()
    return {'type': 'communication', 'id': c.id, 'reference': c.reference, 'reason': f'{c.kind}: {state}.', 'details': {'kind': c.kind, 'state': state}}


@action('contract.register', 'Registrar contrato / garantías previas', 'contract.manage', {'awarded'},
        form=lambda ctx: [F.field('status', 'Estado del contrato', 'select', options=F.options([('not_required', 'No requerido'), ('pending', 'Pendiente de firma'), ('signed', 'Firmado')])),
                          F.field('reference', 'Referencia del contrato', required=False), F.field('reason_not_required', 'Motivo si no se requiere', 'textarea', required=False, rows=2),
                          F.field('document_id', 'Contrato (documento)', 'document', required=False)],
        description='Una orden de compra posterior a la adjudicación exige tener resuelta la formalización y las garantías aplicables.')
def contract_register(ctx, data):
    award = active_award(ctx.case.id)
    status = inp.choice(data, 'status', 'Estado', ('not_required', 'pending', 'signed'))
    doc = doc_in_case(ctx, data.get('document_id'))
    ref = inp.text(data, 'reference', 'Referencia', 2, 200, required=status == 'signed')
    reason = inp.text(data, 'reason_not_required', 'Motivo', 10, 500, required=status == 'not_required')
    row = db.session.scalar(db.select(Contract).where(Contract.award_id == award.id).with_for_update())
    if row:
        require(row.status != 'signed', 'conflict', 'El contrato ya está firmado; no se edita.', 409)
        row.status, row.reference, row.reason_not_required, row.document_id = status, ref, reason, doc.id if doc else row.document_id
    else:
        row = Contract(case_id=ctx.case.id, award_id=award.id, status=status, reference=ref, reason_not_required=reason, document_id=doc.id if doc else None, created_by=ctx.user.id)
        db.session.add(row)
    db.session.flush()
    return {'type': 'contract', 'id': row.id, 'reference': ref, 'reason': f'Contrato: {status}. {reason or ""}'.strip(), 'details': {'status': status}}


def _guarantee_form(ctx):
    existing = db.session.scalars(db.select(Guarantee).where(Guarantee.case_id == ctx.case.id).order_by(Guarantee.id)).all()
    return [F.field('guarantee_id', 'Garantía existente (para actualizar su estado)', 'select', required=False,
                    options=[{'value': g.id, 'label': f'#{g.id} · {g.kind} · {g.status}'} for g in existing]),
            F.field('kind', 'Tipo', 'select', required=False, options=F.options([('mantenimiento', 'Mantenimiento de oferta'), ('fiel_cumplimiento', 'Fiel cumplimiento'), ('otra', 'Otra')])),
            F.field('amount', 'Importe', 'money', required=False), F.field('due_date', 'Vencimiento', 'date', required=False),
            F.field('status', 'Estado', 'select', options=F.options([('required', 'Exigida'), ('received', 'Recibida'), ('returned', 'Devuelta'), ('released', 'Liberada'), ('enforced', 'Ejecutada')])),
            F.field('reference', 'Referencia', required=False), F.field('document_id', 'Constancia (documento)', 'document', required=False)]


@action('guarantee.register', 'Registrar o actualizar garantía', 'contract.manage', {'awarded', 'ordered', 'invoicing', 'closed'}, form=_guarantee_form,
        description='Las garantías y sus vencimientos sobreviven al cierre de la compra.')
def guarantee_register(ctx, data):
    doc = doc_in_case(ctx, data.get('document_id'))
    status = inp.choice(data, 'status', 'Estado', ('required', 'received', 'returned', 'released', 'enforced'))
    gid = data.get('guarantee_id')
    if gid not in (None, ''):
        g = db.session.get(Guarantee, int(gid))
        require(g is not None and g.case_id == ctx.case.id, 'validation', 'Garantía inválida.', 422, {'guarantee_id': 'Inválida.'})
        g.status = status
        g.reference = inp.text(data, 'reference', 'Referencia', 2, 200, required=False) or g.reference
        if doc:
            g.document_id = doc.id
    else:
        contract = db.session.scalar(db.select(Contract).where(Contract.case_id == ctx.case.id))
        g = Guarantee(case_id=ctx.case.id, contract_id=contract.id if contract else None, kind=inp.choice(data, 'kind', 'Tipo', ('mantenimiento', 'fiel_cumplimiento', 'otra')),
                      amount=inp.decimal(data, 'amount', 'Importe', required=False, places=2), due_date=inp.day(data, 'due_date', 'Vencimiento', required=False), status=status,
                      reference=inp.text(data, 'reference', 'Referencia', 2, 200, required=False), document_id=doc.id if doc else None, created_by=ctx.user.id)
        db.session.add(g)
    db.session.flush()
    return {'type': 'guarantee', 'id': g.id, 'reference': g.reference, 'reason': f'Garantía {g.kind}: {status}.', 'details': {'status': status}}


# ---------------------------------------------------------------- orden

def _order_blockers(ctx):
    out = []
    award = active_award(ctx.case.id)
    if award is None:
        return ['No hay adjudicación vigente.']
    comms = db.session.scalars(db.select(Communication).where(Communication.award_id == award.id)).all()
    if not any(c.kind == 'notificacion' and c.state in ('external_constancia', 'integration_confirmed') for c in comms):
        out.append('Falta la constancia de notificación de la adjudicación.')
    try:
        flags = suggest_procedure(ctx.case.estimated_total)['flags'] if ctx.case.currency == 'UYU' else {}
    except ApiError:
        flags = {}
    if flags.get('publicacion_resultados') and not any(c.kind == 'publicacion' and c.state in ('external_constancia', 'integration_confirmed') for c in comms):
        out.append('Falta la constancia de publicación de resultados (art. 50: más de $ 204.800, plazo de diez días).')
    contract = db.session.scalar(db.select(Contract).where(Contract.award_id == award.id))
    if contract is None or contract.status == 'pending':
        out.append('Resolvé la formalización: registrá el contrato firmado o el motivo por el que no se requiere.')
    if flags.get('garantia_cumplimiento_referencia'):
        has = db.session.scalar(db.select(Guarantee.id).where(Guarantee.case_id == ctx.case.id, Guarantee.kind == 'fiel_cumplimiento', Guarantee.status == 'received'))
        if not has and not (contract and contract.status == 'not_required' and contract.reason_not_required):
            out.append('Garantía de cumplimiento (referencia art. 64) pendiente: registrala como recibida o documentá su exención en el contrato.')
    return out


@action('order.issue', 'Emitir la orden de compra', 'order.issue', {'awarded'}, blockers=_order_blockers,
        form=lambda ctx: [F.field('reference', 'Referencia de la orden (opcional)', required=False), F.field('confirm', 'La orden reproduce lo adjudicado sin cambiar precios, cantidades ni condiciones', 'checkbox')],
        description='Se emite después de adjudicación, controles y condiciones previas. No es la solicitud inicial.')
def order_issue(ctx, data):
    require(inp.boolean(data, 'confirm'), 'validation', 'Confirmá que la orden reproduce lo adjudicado.', 422, {'confirm': 'Obligatorio.'})
    award = active_award(ctx.case.id)
    offer = db.session.get(Offer, award.offer_id)
    order = PurchaseOrder(case_id=ctx.case.id, award_id=award.id, code=ctx.case.code.replace('SC-', 'OC-'), currency=award.currency, total=award.amount,
                          supplier_id=offer.supplier_id, issued_by=ctx.user.id)
    db.session.add(order)
    db.session.flush()
    rl = {l.id: l for l in ctx.lines}
    for al in db.session.scalars(db.select(AwardLine).where(AwardLine.award_id == award.id)):
        r = rl[al.request_line_id]
        order.lines.append(OrderLine(request_line_id=r.id, description=r.description, unit=r.unit, quantity=al.quantity, unit_price=al.unit_price, tax_rate=al.tax_rate, amount=al.amount))
    db.session.flush()
    return {'status': 'ordered', 'type': 'purchase_order', 'id': order.id, 'reference': inp.text(data, 'reference', 'Referencia', 2, 200, required=False) or order.code,
            'reason': 'Orden de compra emitida a partir de la adjudicación.', 'details': {'total': dstr(order.total), 'award_id': award.id}}


# ---------------------------------------------------------------- recepción

def _receipt_form(ctx):
    order = order_of(ctx.case.id)
    lines = db.session.scalars(db.select(OrderLine).where(OrderLine.order_id == order.id)).all() if order else []
    return [F.field('reference', 'Referencia del remito / acta de recepción'),
            F.field('lines', 'Cantidades presentadas', 'lines', fields=[
                F.field('order_line_id', 'Renglón', 'select', options=[{'value': l.id, 'label': f'{l.description} · pendiente {dstr(l.quantity - l.accepted_qty)} {l.unit}'} for l in lines]),
                F.field('accepted_qty', 'Aceptada', 'number', required=False), F.field('rejected_qty', 'Rechazada', 'number', required=False),
                F.field('reject_reason', 'Motivo del rechazo', required=False)]),
            F.field('notes', 'Observaciones', 'textarea', required=False, rows=2)]


def _receipt_blockers(ctx):
    order = order_of(ctx.case.id)
    if order is None:
        return ['No hay orden de compra.']
    if all(l.accepted_qty >= l.quantity for l in order.lines):
        return ['Se recibió la totalidad de lo ordenado.']
    return []


def _received_any(ctx):
    o = order_of(ctx.case.id)
    return bool(o) and any(l.accepted_qty > 0 for l in o.lines)


@action('receipt.register', 'Registrar recepción', 'receipt.register', {'ordered', 'invoicing'}, form=_receipt_form, blockers=_receipt_blockers, done=_received_any,
        description='Admite entregas parciales. Lo rechazado no genera conformidad ni saldo facturable; no se puede recibir más de lo ordenado.')
def receipt_register(ctx, data):
    order = order_of(ctx.case.id)
    locked = locked_order_lines(order.id)
    rows = inp.items(data, 'lines', 'Cantidades', 1, 100)
    receipt = Receipt(case_id=ctx.case.id, order_id=order.id, reference=inp.text(data, 'reference', 'Referencia', 2, 200), notes=inp.text(data, 'notes', 'Observaciones', 1, 2000, required=False),
                      received_by=ctx.user.id)
    db.session.add(receipt)
    seen, total_accepted = set(), Decimal(0)
    for i, row in enumerate(rows, 1):
        lid = inp.integer(row, 'order_line_id', f'Línea {i}', minimum=1)
        ol = locked.get(lid)
        require(ol is not None and lid not in seen, 'validation', f'Línea {i}: renglón inválido o repetido.', 422, {'lines': 'Renglón inválido.'})
        seen.add(lid)
        acc = inp.decimal(row, 'accepted_qty', f'Línea {i}: aceptada', required=False, positive=False, places=4, default=Decimal(0))
        rej = inp.decimal(row, 'rejected_qty', f'Línea {i}: rechazada', required=False, positive=False, places=4, default=Decimal(0))
        if acc == 0 and rej == 0:
            continue
        reason = inp.text(row, 'reject_reason', 'Motivo', 3, 300, required=False)
        require(rej == 0 or reason, 'validation', f'Línea {i}: indicá el motivo del rechazo.', 422, {'lines': 'Motivo requerido.'})
        pending = ol.quantity - ol.accepted_qty
        require(acc + rej <= pending, 'over_receipt', f'Línea {i}: la cantidad presentada ({dstr(acc + rej)}) supera el saldo pendiente de la orden ({dstr(pending)}).', 409)
        ol.accepted_qty = ol.accepted_qty + acc
        ol.rejected_qty = ol.rejected_qty + rej
        total_accepted += acc
        receipt.lines.append(ReceiptLine(order_line_id=ol.id, accepted_qty=acc, rejected_qty=rej, reject_reason=reason))
    require(receipt.lines, 'validation', 'Registrá al menos una cantidad aceptada o rechazada.', 422, {'lines': 'Sin cantidades.'})
    db.session.flush()
    return {'type': 'receipt', 'id': receipt.id, 'reference': receipt.reference, 'reason': 'Recepción registrada.', 'details': {'accepted': dstr(total_accepted), 'lines': len(receipt.lines)}}


# ---------------------------------------------------------------- facturación

def _invoice_form(ctx):
    order = order_of(ctx.case.id)
    lines = db.session.scalars(db.select(OrderLine).where(OrderLine.order_id == order.id)).all() if order else []
    return [F.field('doc_type', 'Tipo de comprobante', 'text', default='e-Factura'), F.field('series', 'Serie', required=False), F.field('number', 'Número'),
            F.field('issue_date', 'Fecha de emisión', 'date'), F.field('reference', 'Respaldo', required=False), F.field('document_id', 'Factura (documento)', 'document', required=False),
            F.field('lines', 'Renglones facturados', 'lines', fields=[
                F.field('order_line_id', 'Renglón', 'select', options=[{'value': l.id, 'label': f'{l.description} · recibido sin facturar {dstr(l.accepted_qty - l.invoiced_qty)} {l.unit}'} for l in lines]),
                F.field('quantity', 'Cantidad', 'number'), F.field('unit_price', 'Precio unitario (sin ajustes)', 'money', required=False),
                F.field('adjustment_amount', 'Ajuste documentado (importe)', 'money', required=False), F.field('adjustment_reason', 'Motivo del ajuste', required=False)])]


def _invoice_blockers(ctx):
    order = order_of(ctx.case.id)
    if order is None:
        return ['No hay orden de compra.']
    if not any(l.accepted_qty - l.invoiced_qty > 0 for l in order.lines):
        return ['No hay recepción aceptada pendiente de facturar.']
    return []


@action('invoice.register', 'Registrar factura', 'invoice.register', {'ordered', 'invoicing'}, form=_invoice_form, blockers=_invoice_blockers,
        description='Concilia orden, recepción y factura por renglón y proveedor. Detecta duplicados por emisor, tipo, serie y número.')
def invoice_register(ctx, data):
    order = order_of(ctx.case.id)
    locked = locked_order_lines(order.id)
    rows = inp.items(data, 'lines', 'Renglones', 1, 100)
    number = ''.join(inp.text(data, 'number', 'Número', 1, 30).split()).upper()
    series = ''.join((inp.text(data, 'series', 'Serie', 1, 10, required=False) or '').split()).upper()
    dtype = inp.text(data, 'doc_type', 'Tipo de comprobante', 2, 20).strip()
    doc = doc_in_case(ctx, data.get('document_id'))
    inv = Invoice(case_id=ctx.case.id, order_id=order.id, supplier_id=order.supplier_id, doc_type=dtype, series=series, number=number,
                  issue_date=inp.day(data, 'issue_date', 'Fecha de emisión'), currency=order.currency, total=Decimal(0), reference=inp.text(data, 'reference', 'Respaldo', 1, 200, required=False),
                  document_id=doc.id if doc else None, registered_by=ctx.user.id)
    db.session.add(inv)
    seen, total, adjustments = set(), Decimal(0), Decimal(0)
    for i, row in enumerate(rows, 1):
        lid = inp.integer(row, 'order_line_id', f'Línea {i}', minimum=1)
        ol = locked.get(lid)
        require(ol is not None and lid not in seen, 'validation', f'Línea {i}: renglón inválido o repetido.', 422, {'lines': 'Renglón inválido.'})
        seen.add(lid)
        q = inp.decimal(row, 'quantity', f'Línea {i}: cantidad', places=4)
        available = ol.accepted_qty - ol.invoiced_qty
        require(q <= available, 'over_invoicing', f'Línea {i}: la factura ({dstr(q)}) supera lo recibido conforme pendiente de facturar ({dstr(available)}).', 409)
        price = inp.decimal(row, 'unit_price', f'Línea {i}: precio', required=False, places=4, default=ol.unit_price)
        require(price == ol.unit_price, 'price_mismatch', f'Línea {i}: el precio ({dstr(price)}) difiere del de la orden ({dstr(ol.unit_price)}). Las diferencias se expresan como ajuste documentado, no editando el precio.', 409)
        adj = inp.decimal(row, 'adjustment_amount', f'Línea {i}: ajuste', required=False, positive=False, places=2, default=Decimal(0))
        reason = inp.text(row, 'adjustment_reason', f'Línea {i}: motivo del ajuste', 5, 300, required=adj != 0)
        amount = money(q * price * (1 + ol.tax_rate / 100))
        ol.invoiced_qty = ol.invoiced_qty + q
        adjustments += adj
        total += amount + adj
        inv.lines.append(InvoiceLine(order_line_id=ol.id, quantity=q, unit_price=price, tax_rate=ol.tax_rate, amount=amount, adjustment_amount=adj, adjustment_reason=reason))
    inv.total, inv.adjustment_total = total, adjustments
    require(total > 0, 'validation', 'El total de la factura debe ser mayor que cero.', 422, {'lines': 'Total inválido.'})
    db.session.flush()
    result = {'type': 'invoice', 'id': inv.id, 'reference': f'{dtype} {series}{number}', 'reason': f'Factura registrada por {display2(total)} {inv.currency}.',
              'details': {'total': dstr(total), 'adjustments': dstr(adjustments)}}
    if ctx.case.status == 'ordered':
        result['status'] = 'invoicing'
    return result


def _pending_invoices(ctx, status):
    return db.session.scalars(db.select(Invoice).where(Invoice.case_id == ctx.case.id, Invoice.status.in_(status)).order_by(Invoice.id)).all()


def _invoice_select(ctx, statuses):
    return F.field('invoice_id', 'Factura', 'select', options=[{'value': i.id, 'label': f'{i.doc_type} {i.series}{i.number} · {display2(i.total)} {i.currency} · {i.status}'} for i in _pending_invoices(ctx, statuses)])


def _lock_invoice(ctx, data, statuses):
    inv = db.session.scalar(db.select(Invoice).where(Invoice.id == inp.integer(data, 'invoice_id', 'Factura', minimum=1)).with_for_update().execution_options(populate_existing=True))
    require(inv is not None and inv.case_id == ctx.case.id, 'validation', 'Factura inválida.', 422, {'invoice_id': 'Inválida.'})
    require(inv.status in statuses, 'invalid_state', f'La factura está “{inv.status}”; esta actuación no corresponde.', 409)
    return inv


def _need(statuses):
    return lambda ctx: [] if _pending_invoices(ctx, statuses) else ['No hay facturas en el estado requerido para esta actuación.']


def _step(ctx, inv, step, data, amount=None):
    a = ctx.assignment({'conform': 'invoice.conform', 'control': 'payment.control', 'authorize': 'payment.authorize'}[step])
    db.session.add(InvoiceStep(invoice_id=inv.id, step=step, amount=amount, reference=inp.text(data, 'reference', 'Referencia', 2, 200),
                               reason=inp.text(data, 'reason', 'Fundamento', 5, 2000), author_id=ctx.user.id, assignment_id=a.id if a else None))


@action('invoice.conform', 'Dar conformidad a la factura', 'invoice.conform', {'invoicing'}, blockers=_need(('registered',)),
        form=lambda ctx: [_invoice_select(ctx, ('registered',)), *F.ref_reason('Constancia de conciliación')],
        description='Verifica la correspondencia entre orden, recepción aceptada y factura.')
def invoice_conform(ctx, data):
    inv = _lock_invoice(ctx, data, ('registered',))
    _step(ctx, inv, 'conform', data)
    inv.status = 'conformed'
    return {'type': 'invoice', 'id': inv.id, 'reference': inp.text(data, 'reference', 'Ref', 2, 200), 'reason': 'Conformidad de factura.', 'details': {'total': dstr(inv.total)}}


@action('payment.control', 'Controlar el pago', 'payment.control', {'invoicing'}, blockers=_need(('conformed',)),
        form=lambda ctx: [_invoice_select(ctx, ('conformed',)), F.field('result', 'Resultado', 'select', options=F.options([('sin_observacion', 'Sin observación'), ('observado', 'Observado')])),
                          *F.ref_reason('Fundamento del control')],
        description='Control preventivo del pago. Una observación se conserva y exige una nueva intervención.')
def payment_control(ctx, data):
    inv = _lock_invoice(ctx, data, ('conformed',))
    result = inp.choice(data, 'result', 'Resultado', ('sin_observacion', 'observado'))
    a = ctx.assignment('payment.control')
    iv = Intervention(case_id=ctx.case.id, kind='control_pago', result=result, reference=inp.text(data, 'reference', 'Referencia', 2, 200),
                      reason=inp.text(data, 'reason', 'Fundamento', 5, 4000), invoice_id=inv.id, author_id=ctx.user.id, assignment_id=a.id if a else None)
    db.session.add(iv)
    if result == 'sin_observacion':
        _step(ctx, inv, 'control', data)
        inv.status = 'controlled'
    db.session.flush()
    return {'type': 'invoice', 'id': inv.id, 'reference': iv.reference, 'reason': iv.reason, 'details': {'result': result, 'intervention_id': iv.id}}


AUTH_STATUSES = ('controlled', 'authorized', 'partially_paid')


@action('payment.authorize', 'Autorizar el pago', 'payment.authorize', {'invoicing'}, blockers=_need(AUTH_STATUSES), competence=True,
        form=lambda ctx: [_invoice_select(ctx, AUTH_STATUSES), F.field('amount', 'Importe que se autoriza', 'money', help='Puede ser parcial; no supera el saldo de la factura.'), *F.ref_reason('Fundamento de la autorización')],
        description='La autorización es una actuación del ordenador con competencia vigente; no es la ejecución del pago.')
def payment_authorize(ctx, data):
    inv = _lock_invoice(ctx, data, AUTH_STATUSES)
    amount = inp.decimal(data, 'amount', 'Importe', places=2)
    ctx.require_competence(amount, 'payment.authorize')
    remaining = inv.total - inv.authorized_amount
    require(amount <= remaining, 'over_authorization', f'El importe supera el saldo no autorizado de la factura ({display2(remaining)}).', 409)
    _step(ctx, inv, 'authorize', data, amount)
    inv.authorized_amount = inv.authorized_amount + amount
    if inv.status == 'controlled':
        inv.status = 'authorized'
    db.session.flush()
    return {'type': 'invoice', 'id': inv.id, 'reference': inp.text(data, 'reference', 'Ref', 2, 200), 'reason': f'Pago autorizado por {display2(amount)}.', 'details': {'amount': dstr(amount)}}


def _payable(ctx):
    return [i for i in _pending_invoices(ctx, ('authorized', 'partially_paid')) if i.authorized_amount > i.paid_amount]


@action('payment.record', 'Registrar la ejecución del pago', 'payment.record', {'invoicing'},
        blockers=lambda ctx: [] if _payable(ctx) else ['No hay pagos autorizados pendientes de ejecución.'],
        form=lambda ctx: [F.field('invoice_id', 'Factura', 'select', options=[{'value': i.id, 'label': f'{i.doc_type} {i.series}{i.number} · autorizado sin pagar {display2(i.authorized_amount - i.paid_amount)}'} for i in _payable(ctx)]),
                          F.field('amount', 'Importe pagado', 'money'), F.field('proof_reference', 'Comprobante de pago (referencia)', help='Registro con comprobante. No prueba por sí solo una transferencia bancaria.'),
                          F.field('executed_on', 'Fecha de ejecución', 'date'), F.field('proof_document_id', 'Comprobante (documento)', 'document', required=False),
                          F.field('payment_key', 'Clave de operación', 'hidden', required=False)],
        description='Registra un pago ya ejecutado, con comprobante. La aplicación no mueve dinero ni envía órdenes bancarias.')
def payment_record(ctx, data):
    inv = _lock_invoice(ctx, data, ('authorized', 'partially_paid'))
    amount = inp.decimal(data, 'amount', 'Importe', places=2)
    owed = inv.authorized_amount - inv.paid_amount
    require(amount <= owed, 'overpayment', f'El pago ({display2(amount)}) supera lo autorizado pendiente ({display2(owed)}).', 409)
    doc = doc_in_case(ctx, data.get('proof_document_id'))
    proof = inp.text(data, 'proof_reference', 'Comprobante', 3, 200)
    key = inp.text(data, 'payment_key', 'Clave', 8, 80, required=False) or canonical_hash({'i': inv.id, 'a': dstr(amount), 'p': proof})[:40]
    p = Payment(case_id=ctx.case.id, invoice_id=inv.id, amount=amount, proof_reference=proof, proof_document_id=doc.id if doc else None,
                executed_on=inp.day(data, 'executed_on', 'Fecha de ejecución'), idempotency_key=key, recorded_by=ctx.user.id)
    db.session.add(p)
    inv.paid_amount = inv.paid_amount + amount
    inv.status = 'paid' if inv.paid_amount == inv.total else 'partially_paid'
    db.session.flush()
    return {'type': 'payment', 'id': p.id, 'reference': proof, 'reason': f'Pago registrado por {display2(amount)} (registro manual con comprobante).', 'details': {'invoice_id': inv.id, 'amount': dstr(amount), 'mode': 'manual_record'}}


# ---------------------------------------------------------------- modificaciones contractuales

def _mod_form(ctx):
    order = order_of(ctx.case.id)
    lines = db.session.scalars(db.select(OrderLine).where(OrderLine.order_id == order.id)).all() if order else []
    return [F.field('kind', 'Tipo', 'select', options=F.options([('ampliacion', 'Ampliación'), ('disminucion', 'Disminución'), ('prorroga', 'Prórroga'), ('otra', 'Otra')])),
            F.field('grounds', 'Fundamento y encuadre normativo', 'textarea', rows=4, help='Ver TOCAF art. 74; los límites no están parametrizados y requieren validación jurídica.'),
            F.field('changes', 'Nuevas cantidades', 'lines', fields=[
                F.field('order_line_id', 'Renglón', 'select', options=[{'value': l.id, 'label': f'{l.description} · actual {dstr(l.quantity)}'} for l in lines]),
                F.field('new_quantity', 'Nueva cantidad', 'number')])]


@action('modification.propose', 'Proponer modificación contractual', 'modification.propose', {'ordered', 'invoicing'}, form=_mod_form, blockers=lambda ctx: [] if order_of(ctx.case.id) else ['No hay orden.'],
        description='Una modificación es una entidad versionada y autorizada; nunca una edición silenciosa de la orden.')
def modification_propose(ctx, data):
    order = order_of(ctx.case.id)
    locked = locked_order_lines(order.id)
    changes = []
    for i, row in enumerate(inp.items(data, 'changes', 'Cambios', 1, 100), 1):
        lid = inp.integer(row, 'order_line_id', f'Cambio {i}', minimum=1)
        ol = locked.get(lid)
        require(ol is not None, 'validation', f'Cambio {i}: renglón inválido.', 422, {'changes': 'Inválido.'})
        newq = inp.decimal(row, 'new_quantity', f'Cambio {i}: cantidad', places=4)
        require(newq >= ol.accepted_qty and newq >= ol.invoiced_qty, 'validation', f'Cambio {i}: la nueva cantidad no puede ser menor que lo recibido o facturado.', 422, {'changes': 'Menor a lo recibido.'})
        changes.append({'order_line_id': lid, 'old_quantity': dstr(ol.quantity), 'new_quantity': dstr(newq)})
    seq = (db.session.scalar(db.select(db.func.max(ContractModification.sequence)).where(ContractModification.order_id == order.id)) or 0) + 1
    m = ContractModification(case_id=ctx.case.id, order_id=order.id, sequence=seq, kind=inp.choice(data, 'kind', 'Tipo', ('ampliacion', 'disminucion', 'prorroga', 'otra')),
                             grounds=inp.text(data, 'grounds', 'Fundamento', 20, 4000), changes=changes, proposed_by=ctx.user.id,
                             limit_check={'status': 'pending_validation', 'message': 'Los límites de ampliación/disminución no están parametrizados: requieren validación jurídica y control.'})
    db.session.add(m)
    db.session.flush()
    return {'type': 'contract_modification', 'id': m.id, 'reference': f'MOD-{seq}', 'reason': m.grounds, 'details': {'changes': changes}}


def _open_mods(ctx):
    return db.session.scalars(db.select(ContractModification).where(ContractModification.case_id == ctx.case.id, ContractModification.status == 'proposed')).all()


@action('modification.decide', 'Resolver modificación contractual', 'modification.approve', {'ordered', 'invoicing'}, competence=True,
        form=lambda ctx: [F.field('modification_id', 'Modificación', 'select', options=[{'value': m.id, 'label': f'MOD-{m.sequence} · {m.kind}'} for m in _open_mods(ctx)]),
                          F.field('decision', 'Decisión', 'select', options=F.options([('approved', 'Aprobar'), ('rejected', 'Rechazar')])), *F.ref_reason('Fundamento'),
                          F.field('control_reference', 'Referencia del control aplicable', required=False, help='Intervención preventiva del gasto sobre la modificación (obligatoria al aprobar).')],
        blockers=lambda ctx: [] if _open_mods(ctx) else ['No hay modificaciones propuestas.'],
        description='Solo el ordenador con competencia aprueba; la orden pasa a una nueva versión y conserva la anterior.')
def modification_decide(ctx, data):
    m = db.session.get(ContractModification, inp.integer(data, 'modification_id', 'Modificación', minimum=1))
    require(m is not None and m.case_id == ctx.case.id and m.status == 'proposed', 'validation', 'Modificación inválida.', 422, {'modification_id': 'Inválida.'})
    decision = inp.choice(data, 'decision', 'Decisión', ('approved', 'rejected'))
    ctx.require_competence(None, 'modification.approve')
    m.status, m.decided_by, m.decided_at = decision, ctx.user.id, utcnow()
    m.decision_reference = inp.text(data, 'reference', 'Referencia', 2, 200)
    if decision == 'approved':
        inp.text(data, 'control_reference', 'Control', 3, 200)
        order = db.session.get(PurchaseOrder, m.order_id)
        locked = locked_order_lines(order.id)
        for ch in m.changes:
            ol = locked[ch['order_line_id']]
            newq = Decimal(ch['new_quantity'])
            require(newq >= ol.accepted_qty and newq >= ol.invoiced_qty, 'quantity_conflict', 'La nueva cantidad quedó por debajo de lo recibido o facturado.', 409)
            ol.quantity = newq
            ol.amount = money(newq * ol.unit_price * (1 + ol.tax_rate / 100))
        order.total = sum((l.amount for l in locked.values()), Decimal(0))
        order.version += 1
    db.session.flush()
    return {'type': 'contract_modification', 'id': m.id, 'reference': m.decision_reference, 'reason': inp.text(data, 'reason', 'Fundamento', 5, 2000), 'details': {'decision': decision}}


# ---------------------------------------------------------------- cierre

def _close_blockers(ctx):
    order = order_of(ctx.case.id)
    out = []
    if order is None:
        return ['No hay orden de compra.']
    if any(l.accepted_qty < l.quantity for l in order.lines):
        out.append('Falta recibir la totalidad de lo ordenado.')
    if any(l.invoiced_qty < l.accepted_qty for l in order.lines):
        out.append('Hay recepción aceptada sin facturar.')
    invs = db.session.scalars(db.select(Invoice).where(Invoice.case_id == ctx.case.id)).all()
    if not invs:
        out.append('No hay facturas registradas.')
    if any(i.paid_amount != i.total for i in invs):
        out.append('Hay facturas sin pago conciliado.')
    return out


@action('case.close', 'Cerrar la compra', 'case.close', {'invoicing'}, blockers=_close_blockers,
        form=lambda ctx: F.ref_reason('Constancia de cierre'),
        description='El cierre administrativo no extingue garantías ni obligaciones posteriores, que permanecen registradas.')
def case_close(ctx, data):
    pending = [{'guarantee_id': g.id, 'kind': g.kind, 'status': g.status, 'due_date': g.due_date.isoformat() if g.due_date else None, 'amount': dstr(g.amount) if g.amount is not None else None}
               for g in db.session.scalars(db.select(Guarantee).where(Guarantee.case_id == ctx.case.id, Guarantee.status.in_(('required', 'received'))))]
    ref = inp.text(data, 'reference', 'Referencia', 2, 200)
    db.session.add(CaseClosure(case_id=ctx.case.id, reason=inp.text(data, 'reason', 'Constancia', 5, 2000), reference=ref, pending_obligations=pending, closed_by=ctx.user.id))
    ctx.case.closed_at = utcnow()
    db.session.flush()
    return {'status': 'closed', 'type': 'case', 'id': ctx.case.id, 'reference': ref, 'reason': 'Compra cerrada.', 'details': {'pending_obligations': pending}}
