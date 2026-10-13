"""Comunicación, contrato/garantías, orden, recepción, facturación, pago y cierre."""
from app.extensions import db
from .base import ts, ts_null, fk, Money, Qty, Rate


class Communication(db.Model):
    __tablename__ = 'communication'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    award_id = fk('award.id')
    kind = db.Column(db.String(20), nullable=False)  # notificacion | publicacion
    state = db.Column(db.String(24), nullable=False)  # pending | external_constancia | integration_confirmed
    recipients = db.Column(db.String(300))
    reference = db.Column(db.String(200))
    document_id = fk('document.id', nullable=True)
    note = db.Column(db.String(500))
    created_by = fk('user.id')
    created_at = ts()


class Contract(db.Model):
    __tablename__ = 'contract'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    award_id = fk('award.id')
    status = db.Column(db.String(14), nullable=False)  # not_required | pending | signed
    reference = db.Column(db.String(200))
    reason_not_required = db.Column(db.String(500))
    document_id = fk('document.id', nullable=True)
    created_by = fk('user.id')
    created_at = ts()
    __table_args__ = (db.UniqueConstraint('award_id', name='uq_contract_award'),)


class Guarantee(db.Model):
    __tablename__ = 'guarantee'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    contract_id = fk('contract.id', nullable=True)
    kind = db.Column(db.String(20), nullable=False)  # mantenimiento | fiel_cumplimiento | otra
    amount = db.Column(Money)
    due_date = db.Column(db.Date)
    status = db.Column(db.String(12), nullable=False, default='required')  # required | received | returned | released | enforced
    reference = db.Column(db.String(200))
    document_id = fk('document.id', nullable=True)
    created_by = fk('user.id')
    created_at = ts()


class PurchaseOrder(db.Model):
    __tablename__ = 'purchase_order'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    award_id = fk('award.id')
    code = db.Column(db.String(30), unique=True, nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(12), nullable=False, default='active')
    currency = db.Column(db.String(3), nullable=False)
    total = db.Column(Money, nullable=False)
    supplier_id = fk('supplier.id')
    issued_by = fk('user.id')
    issued_at = ts()
    lines = db.relationship('OrderLine', backref='order', order_by='OrderLine.id', cascade='all, delete-orphan')
    __table_args__ = (db.UniqueConstraint('award_id', name='uq_order_award'),)


class OrderLine(db.Model):
    __tablename__ = 'order_line'
    id = db.Column(db.Integer, primary_key=True)
    order_id = fk('purchase_order.id', ondelete='CASCADE')
    request_line_id = fk('request_line.id')
    description = db.Column(db.String(300), nullable=False)
    unit = db.Column(db.String(30), nullable=False)
    quantity = db.Column(Qty, nullable=False)
    unit_price = db.Column(Qty, nullable=False)
    tax_rate = db.Column(Rate, nullable=False)
    amount = db.Column(Money, nullable=False)
    accepted_qty = db.Column(Qty, nullable=False, default=0)
    rejected_qty = db.Column(Qty, nullable=False, default=0)
    invoiced_qty = db.Column(Qty, nullable=False, default=0)
    __table_args__ = (db.CheckConstraint('accepted_qty >= 0 AND invoiced_qty >= 0 AND accepted_qty <= quantity AND invoiced_qty <= accepted_qty', name='ck_order_line_qty'),)


class ContractModification(db.Model):
    __tablename__ = 'contract_modification'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    order_id = fk('purchase_order.id')
    sequence = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(20), nullable=False)  # ampliacion | disminucion | prorroga | otra
    status = db.Column(db.String(12), nullable=False, default='proposed')  # proposed | approved | rejected
    grounds = db.Column(db.Text, nullable=False)
    changes = db.Column(db.JSON, nullable=False)  # [{order_line_id, new_quantity}]
    limit_check = db.Column(db.JSON)
    control_id = fk('intervention.id', nullable=True)
    proposed_by = fk('user.id')
    decided_by = fk('user.id', nullable=True)
    decision_reference = db.Column(db.String(200))
    created_at = ts()
    decided_at = ts_null()
    __table_args__ = (db.UniqueConstraint('order_id', 'sequence', name='uq_modification_seq'),)


class Receipt(db.Model):
    __tablename__ = 'receipt'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    order_id = fk('purchase_order.id')
    reference = db.Column(db.String(200), nullable=False)
    notes = db.Column(db.Text)
    received_by = fk('user.id')
    received_at = ts()
    lines = db.relationship('ReceiptLine', backref='receipt', cascade='all, delete-orphan')


class ReceiptLine(db.Model):
    __tablename__ = 'receipt_line'
    id = db.Column(db.Integer, primary_key=True)
    receipt_id = fk('receipt.id', ondelete='CASCADE')
    order_line_id = fk('order_line.id')
    accepted_qty = db.Column(Qty, nullable=False, default=0)
    rejected_qty = db.Column(Qty, nullable=False, default=0)
    reject_reason = db.Column(db.String(300))


class Invoice(db.Model):
    __tablename__ = 'invoice'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    order_id = fk('purchase_order.id')
    supplier_id = fk('supplier.id')
    doc_type = db.Column(db.String(20), nullable=False)  # e-factura, e-ticket, nota de crédito ...
    series = db.Column(db.String(10), nullable=False, default='')
    number = db.Column(db.String(30), nullable=False)
    issue_date = db.Column(db.Date, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    total = db.Column(Money, nullable=False)
    status = db.Column(db.String(14), nullable=False, default='registered')
    # registered | conformed | controlled | authorized | partially_paid | paid
    reference = db.Column(db.String(200))
    document_id = fk('document.id', nullable=True)
    adjustment_total = db.Column(Money, nullable=False, default=0)
    authorized_amount = db.Column(Money, nullable=False, default=0)
    paid_amount = db.Column(Money, nullable=False, default=0)
    registered_by = fk('user.id')
    created_at = ts()
    lines = db.relationship('InvoiceLine', backref='invoice', cascade='all, delete-orphan')
    __table_args__ = (db.UniqueConstraint('supplier_id', 'doc_type', 'series', 'number', name='uq_invoice_identity'),
                      db.CheckConstraint('paid_amount <= authorized_amount', name='ck_invoice_paid_le_authorized'))


class InvoiceLine(db.Model):
    __tablename__ = 'invoice_line'
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = fk('invoice.id', ondelete='CASCADE')
    order_line_id = fk('order_line.id')
    quantity = db.Column(Qty, nullable=False)
    unit_price = db.Column(Qty, nullable=False)
    tax_rate = db.Column(Rate, nullable=False)
    amount = db.Column(Money, nullable=False)
    adjustment_amount = db.Column(Money, nullable=False, default=0)
    adjustment_reason = db.Column(db.String(300))


class InvoiceStep(db.Model):
    """Conformidad, control y autorización de cada factura (atribuidos, con respaldo)."""
    __tablename__ = 'invoice_step'
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = fk('invoice.id')
    step = db.Column(db.String(12), nullable=False)  # conform | control | authorize
    amount = db.Column(Money)
    reference = db.Column(db.String(200), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    author_id = fk('user.id')
    assignment_id = fk('user_role.id', nullable=True)
    created_at = ts()


class Payment(db.Model):
    __tablename__ = 'payment'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    invoice_id = fk('invoice.id')
    amount = db.Column(Money, nullable=False)
    execution_mode = db.Column(db.String(20), nullable=False, default='manual_record')
    # manual_record: registro con comprobante; integration: ejecutado por un sistema financiero conectado (no disponible)
    proof_reference = db.Column(db.String(200), nullable=False)
    proof_document_id = fk('document.id', nullable=True)
    executed_on = db.Column(db.Date, nullable=False)
    idempotency_key = db.Column(db.String(80), nullable=False)
    recorded_by = fk('user.id')
    created_at = ts()
    __table_args__ = (db.UniqueConstraint('invoice_id', 'proof_reference', name='uq_payment_proof'),
                      db.UniqueConstraint('invoice_id', 'idempotency_key', name='uq_payment_idem'))


class CaseClosure(db.Model):
    __tablename__ = 'case_closure'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    reason = db.Column(db.Text, nullable=False)
    reference = db.Column(db.String(200), nullable=False)
    pending_obligations = db.Column(db.JSON, nullable=False)
    closed_by = fk('user.id')
    closed_at = ts()
    __table_args__ = (db.UniqueConstraint('case_id', name='uq_closure_case'),)
