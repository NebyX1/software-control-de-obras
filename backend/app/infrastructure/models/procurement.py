"""Solicitud, preparación, pliegos, recepción de ofertas, evaluación y decisión."""
from app.extensions import db
from .base import ts, ts_null, fk, Money, Qty, Rate, Score


class ProcurementCase(db.Model):
    __tablename__ = 'procurement_case'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)  # SC-AAAA-NNNN: estable, usado en URLs
    title = db.Column(db.String(200), nullable=False)
    area_id = fk('area.id')
    requester_id = fk('user.id')
    status = db.Column(db.String(24), nullable=False, default='draft', index=True)
    stage = db.Column(db.Integer, nullable=False, default=0)  # 0..7 gestionado solo por el servidor
    version = db.Column(db.Integer, nullable=False, default=1)  # control optimista de concurrencia
    need_text = db.Column(db.Text, nullable=False)
    delivery_place = db.Column(db.String(200))
    currency = db.Column(db.String(3), nullable=False, default='UYU')
    estimated_total = db.Column(Money, nullable=False)  # estimación con impuestos; NO es crédito disponible
    procedure_type = db.Column(db.String(30))  # compra_directa | concurso_precios | licitacion_abreviada | licitacion_publica | convenio_marco | excepcion
    procedure_basis = db.Column(db.JSON)  # sugerencia por monto + decisión de Compras + regla aplicada
    branch = db.Column(db.JSON)  # rama activa: cancelada, desierta, ofertas rechazadas, excepción...
    flags = db.Column(db.JSON, nullable=False, default=dict)
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    created_at = ts()
    updated_at = db.Column(db.DateTime, nullable=True)
    submitted_at = ts_null()
    closed_at = ts_null()
    area = db.relationship('Area')
    requester = db.relationship('User', foreign_keys=[requester_id])


class RequestLine(db.Model):
    __tablename__ = 'request_line'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id', ondelete='CASCADE')
    position = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(300), nullable=False)
    quantity = db.Column(Qty, nullable=False)
    unit = db.Column(db.String(30), nullable=False)
    estimated_unit_price = db.Column(Qty)
    tax_rate = db.Column(Rate)
    __table_args__ = (db.UniqueConstraint('case_id', 'position', name='uq_request_line_pos'),)


class BudgetLine(db.Model):
    """Crédito registrado manualmente con respaldo. No sustituye al sistema financiero (SIFI)."""
    __tablename__ = 'budget_line'
    id = db.Column(db.Integer, primary_key=True)
    fiscal_year = db.Column(db.Integer, nullable=False)
    item = db.Column(db.String(60), nullable=False)  # rubro / objeto del gasto
    funding_source = db.Column(db.String(80), nullable=False)
    total_amount = db.Column(Money, nullable=False)
    committed_amount = db.Column(Money, nullable=False, default=0)
    support_ref = db.Column(db.String(200), nullable=False)
    support_document_id = fk('document.id', nullable=True)
    registered_by = fk('user.id')
    created_at = ts()
    __table_args__ = (db.UniqueConstraint('fiscal_year', 'item', 'funding_source', name='uq_budget_line'),)


class Availability(db.Model):
    __tablename__ = 'availability'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    budget_line_id = fk('budget_line.id')
    amount = db.Column(Money, nullable=False)
    fiscal_year = db.Column(db.Integer, nullable=False)
    budget_item = db.Column(db.String(60), nullable=False)
    funding_source = db.Column(db.String(80), nullable=False)
    availability_date = db.Column(db.Date, nullable=False)
    support_ref = db.Column(db.String(200), nullable=False)
    support_document_id = fk('document.id', nullable=True)
    status = db.Column(db.String(12), nullable=False, default='active')  # active | revoked
    active_key = db.Column(db.SmallInteger, default=1)  # 1 mientras está activa; NULL al revocarla
    registered_by = fk('user.id')
    created_at = ts()
    revoked_at = ts_null()
    __table_args__ = (db.UniqueConstraint('case_id', 'active_key', name='uq_availability_active'),)


class SpecVersion(db.Model):
    """Pliego/condiciones versionados. Aprobado = inmutable; cambios generan una nueva versión."""
    __tablename__ = 'spec_version'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id', ondelete='CASCADE')
    version = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(12), nullable=False, default='draft')  # draft | approved | superseded
    mode = db.Column(db.String(12), nullable=False, default='min_price')  # weighted | min_price | framework
    currency = db.Column(db.String(3), nullable=False, default='UYU')
    fx = db.Column(db.JSON)  # tipos de cambio fijados por el pliego: {USD: {rate, date, source}}
    minimum_text = db.Column(db.Text, nullable=False)
    delivery_terms = db.Column(db.String(60))
    flags = db.Column(db.JSON, nullable=False, default=dict)  # preferences, partial_award
    similarity_margin = db.Column(db.Numeric(6, 4), nullable=False, default=0.05)
    offer_deadline = ts_null()
    reception_channel = db.Column(db.String(30))
    reception_place = db.Column(db.String(200))
    change_reason = db.Column(db.String(500))
    content_hash = db.Column(db.String(64))
    created_by = fk('user.id')
    created_at = ts()
    approved_by = fk('user.id', nullable=True)
    approved_at = ts_null()
    requirements = db.relationship('SpecRequirement', backref='spec', order_by='SpecRequirement.position', cascade='all, delete-orphan')
    criteria = db.relationship('SpecCriterion', backref='spec', order_by='SpecCriterion.position', cascade='all, delete-orphan')
    __table_args__ = (db.UniqueConstraint('case_id', 'version', name='uq_spec_version'),)


class SpecRequirement(db.Model):
    __tablename__ = 'spec_requirement'
    id = db.Column(db.Integer, primary_key=True)
    spec_version_id = fk('spec_version.id', ondelete='CASCADE')
    position = db.Column(db.Integer, nullable=False)
    code = db.Column(db.String(20), nullable=False)
    text = db.Column(db.String(500), nullable=False)
    essential = db.Column(db.Boolean, nullable=False, default=True)
    kind = db.Column(db.String(10), nullable=False, default='review')  # review | numeric
    attribute = db.Column(db.String(30))  # delivery_days | warranty_months
    operator = db.Column(db.String(4))
    threshold = db.Column(db.Numeric(18, 4))
    unit = db.Column(db.String(20))


class SpecCriterion(db.Model):
    __tablename__ = 'spec_criterion'
    id = db.Column(db.Integer, primary_key=True)
    spec_version_id = fk('spec_version.id', ondelete='CASCADE')
    position = db.Column(db.Integer, nullable=False)
    code = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    weight = db.Column(db.Numeric(10, 4), nullable=False)
    type = db.Column(db.String(12), nullable=False)  # price_ratio | scale | manual
    attribute = db.Column(db.String(30))
    scale = db.Column(db.JSON)
    description = db.Column(db.String(500))


class CaseAuthorization(db.Model):
    """Autorización del llamado por el ordenador, con competencia vigente."""
    __tablename__ = 'case_authorization'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    kind = db.Column(db.String(20), nullable=False)  # call
    spec_version_id = fk('spec_version.id', nullable=True)
    reference = db.Column(db.String(200), nullable=False)
    grounds = db.Column(db.Text, nullable=False)
    assignment_id = fk('user_role.id', nullable=True)
    authorized_by = fk('user.id')
    status = db.Column(db.String(12), nullable=False, default='active')
    created_at = ts()


class PublicityRecord(db.Model):
    __tablename__ = 'publicity_record'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    spec_version_id = fk('spec_version.id', nullable=True)
    kind = db.Column(db.String(20), nullable=False)  # convocatoria | invitacion | adjudicacion
    state = db.Column(db.String(24), nullable=False)  # pending | external_constancia | integration_confirmed
    reference = db.Column(db.String(200))
    published_at = ts_null()
    document_id = fk('document.id', nullable=True)
    notice_note = db.Column(db.String(500))
    created_by = fk('user.id')
    created_at = ts()


class Envelope(db.Model):
    __tablename__ = 'envelope'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    spec_version_id = fk('spec_version.id')
    supplier_id = fk('supplier.id')
    receipt_code = db.Column(db.String(30), unique=True, nullable=False)
    round = db.Column(db.Integer, nullable=False, default=1)
    channel = db.Column(db.String(30), nullable=False)
    received_at = ts()  # hora del servidor, UTC; se presenta en America/Montevideo
    deadline_at = db.Column(db.DateTime, nullable=False)  # plazo vigente al momento de la recepción
    on_time = db.Column(db.Boolean, nullable=False)
    custody_note = db.Column(db.String(300), nullable=False)
    status = db.Column(db.String(12), nullable=False, default='received')  # received | late | withdrawn
    opened_at = ts_null()
    created_by = fk('user.id')
    supplier = db.relationship('Supplier')
    __table_args__ = (db.UniqueConstraint('case_id', 'supplier_id', 'round', name='uq_envelope_supplier'),)


class DeadlineExtension(db.Model):
    __tablename__ = 'deadline_extension'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    previous_deadline = db.Column(db.DateTime, nullable=False)
    new_deadline = db.Column(db.DateTime, nullable=False)
    reason = db.Column(db.String(500), nullable=False)
    communicated_ref = db.Column(db.String(200), nullable=False)  # comunicación uniforme a todos los interesados
    created_by = fk('user.id')
    created_at = ts()


class OpeningRecord(db.Model):
    __tablename__ = 'opening_record'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    opened_at = ts()
    reference = db.Column(db.String(200), nullable=False)
    participants = db.Column(db.JSON, nullable=False)
    minutes_document_id = fk('document.id', nullable=True)
    envelope_count = db.Column(db.Integer, nullable=False)
    round = db.Column(db.Integer, nullable=False, default=1)
    notes = db.Column(db.Text)
    created_by = fk('user.id')
    __table_args__ = (db.UniqueConstraint('case_id', 'round', name='uq_opening_case'),)


class Offer(db.Model):
    """Datos de la oferta (liberados solo tras la apertura). Se versionan: cada cambio crea una `data_version`."""
    __tablename__ = 'offer'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    envelope_id = fk('envelope.id')
    supplier_id = fk('supplier.id')
    currency = db.Column(db.String(3), nullable=False, default='UYU')
    data_version = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(16), nullable=False, default='pending_data')  # pending_data | data_recorded
    created_at = ts()
    supplier = db.relationship('Supplier')
    __table_args__ = (db.UniqueConstraint('envelope_id', name='uq_offer_envelope'),)


class OfferDataVersion(db.Model):
    __tablename__ = 'offer_data_version'
    id = db.Column(db.Integer, primary_key=True)
    offer_id = fk('offer.id')
    version = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    prices_include_tax = db.Column(db.Boolean, nullable=False, default=False)
    freight = db.Column(Money, nullable=False, default=0)
    freight_includes_tax = db.Column(db.Boolean, nullable=False, default=True)
    freight_tax_rate = db.Column(Rate, nullable=False, default=0)
    discount_total = db.Column(Money, nullable=False, default=0)
    delivery_days = db.Column(db.Integer)
    warranty_months = db.Column(db.Integer)
    delivery_terms = db.Column(db.String(60))
    evidence = db.Column(db.JSON)  # {campo: {document_id, page, quote}}
    reason = db.Column(db.String(500))
    recorded_by = fk('user.id')
    created_at = ts()
    lines = db.relationship('OfferLine', backref='data', order_by='OfferLine.request_line_id', cascade='all, delete-orphan')
    __table_args__ = (db.UniqueConstraint('offer_id', 'version', name='uq_offer_data_version'),)


class OfferLine(db.Model):
    __tablename__ = 'offer_line'
    id = db.Column(db.Integer, primary_key=True)
    data_version_id = fk('offer_data_version.id', ondelete='CASCADE')
    request_line_id = fk('request_line.id')
    unit_price = db.Column(Qty, nullable=False)
    quantity = db.Column(Qty)
    tax_rate = db.Column(Rate, nullable=False)
    discount = db.Column(Money, nullable=False, default=0)


class RequirementReview(db.Model):
    """Revisión atribuida por requisito. Append-only: la vigente es la última por (oferta, requisito)."""
    __tablename__ = 'requirement_review'
    id = db.Column(db.Integer, primary_key=True)
    offer_id = fk('offer.id')
    requirement_id = fk('spec_requirement.id')
    result = db.Column(db.String(10), nullable=False)  # met | not_met | pending
    treatment = db.Column(db.String(14))  # subsanable | no_subsanable
    observed_value = db.Column(db.String(200))
    document_id = fk('document.id', nullable=True)
    page = db.Column(db.Integer)
    quote = db.Column(db.String(600))
    note = db.Column(db.String(500))
    reviewer_id = fk('user.id')
    reviewed_at = ts()


class ManualScore(db.Model):
    __tablename__ = 'manual_score'
    id = db.Column(db.Integer, primary_key=True)
    offer_id = fk('offer.id')
    criterion_id = fk('spec_criterion.id')
    points = db.Column(db.Numeric(10, 4), nullable=False)
    evidence = db.Column(db.String(600), nullable=False)
    evaluator_id = fk('user.id')
    created_at = ts()


class ExtractedField(db.Model):
    __tablename__ = 'extracted_field'
    id = db.Column(db.Integer, primary_key=True)
    document_version_id = fk('document_version.id')
    offer_id = fk('offer.id', nullable=True)
    task_id = fk('background_task.id', nullable=True)
    field_key = db.Column(db.String(40), nullable=False)
    proposed_value = db.Column(db.String(200))
    page = db.Column(db.Integer)
    quote = db.Column(db.String(600))
    evidence_verified = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(12), nullable=False, default='proposed')  # proposed | confirmed | corrected | rejected
    model = db.Column(db.String(80))
    created_at = ts()


class FieldReview(db.Model):
    __tablename__ = 'field_review'
    id = db.Column(db.Integer, primary_key=True)
    field_id = fk('extracted_field.id')
    action = db.Column(db.String(10), nullable=False)  # confirm | correct | reject
    value = db.Column(db.String(200))
    note = db.Column(db.String(500))
    reviewer_id = fk('user.id')
    created_at = ts()


class Evaluation(db.Model):
    __tablename__ = 'evaluation'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    version = db.Column(db.Integer, nullable=False)
    spec_version_id = fk('spec_version.id')
    mode = db.Column(db.String(12), nullable=False)
    status = db.Column(db.String(12), nullable=False, default='current')  # current | stale | superseded
    stale_reason = db.Column(db.String(300))
    stale_at = ts_null()
    engine_version = db.Column(db.String(12), nullable=False)
    input_hash = db.Column(db.String(64), nullable=False)
    inputs = db.Column(db.JSON, nullable=False)  # entradas exactas
    result = db.Column(db.JSON, nullable=False)
    recommended_offer_id = fk('offer.id', nullable=True)
    created_by = fk('user.id')
    created_at = ts()
    __table_args__ = (db.UniqueConstraint('case_id', 'version', name='uq_evaluation_version'),)


class Opinion(db.Model):
    __tablename__ = 'opinion'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    evaluation_id = fk('evaluation.id')
    recommended_offer_id = fk('offer.id')
    reference = db.Column(db.String(200), nullable=False)
    grounds = db.Column(db.Text, nullable=False)
    document_id = fk('document.id', nullable=True)
    author_id = fk('user.id')
    assignment_id = fk('user_role.id', nullable=True)
    status = db.Column(db.String(12), nullable=False, default='active')  # active | outdated
    created_at = ts()


class Intervention(db.Model):
    """Control preventivo del gasto/pago. Una observación se conserva; la respuesta es otra actuación."""
    __tablename__ = 'intervention'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    kind = db.Column(db.String(16), nullable=False)  # control_gasto | control_pago
    result = db.Column(db.String(16), nullable=False)  # sin_observacion | observado
    reference = db.Column(db.String(200), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    evaluation_id = fk('evaluation.id', nullable=True)
    offer_id = fk('offer.id', nullable=True)
    invoice_id = db.Column(db.Integer, nullable=True, index=True)  # sin FK: evita el ciclo intervention → invoice → purchase_order → award → intervention
    author_id = fk('user.id')
    assignment_id = fk('user_role.id', nullable=True)
    status = db.Column(db.String(12), nullable=False, default='active')  # active | outdated
    created_at = ts()


class ObservationResponse(db.Model):
    __tablename__ = 'observation_response'
    id = db.Column(db.Integer, primary_key=True)
    intervention_id = fk('intervention.id')
    reference = db.Column(db.String(200), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    document_id = fk('document.id', nullable=True)
    author_id = fk('user.id')
    created_at = ts()


class Award(db.Model):
    __tablename__ = 'award'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    evaluation_id = fk('evaluation.id')
    offer_id = fk('offer.id')
    offer_data_version = db.Column(db.Integer, nullable=False)
    amount = db.Column(Money, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    opinion_id = fk('opinion.id', nullable=True)
    control_id = fk('intervention.id')
    reference = db.Column(db.String(200), nullable=False)
    grounds = db.Column(db.Text, nullable=False)
    departure_reason = db.Column(db.Text)
    assignment_id = fk('user_role.id')
    authority_snapshot = db.Column(db.JSON, nullable=False)
    awarded_by = fk('user.id')
    status = db.Column(db.String(10), nullable=False, default='active')
    active_key = db.Column(db.SmallInteger, default=1)
    created_at = ts()
    lines = db.relationship('AwardLine', backref='award', cascade='all, delete-orphan')
    __table_args__ = (db.UniqueConstraint('case_id', 'active_key', name='uq_award_active'),)


class AwardLine(db.Model):
    __tablename__ = 'award_line'
    id = db.Column(db.Integer, primary_key=True)
    award_id = fk('award.id', ondelete='CASCADE')
    request_line_id = fk('request_line.id')
    quantity = db.Column(Qty, nullable=False)
    unit_price = db.Column(Qty, nullable=False)
    tax_rate = db.Column(Rate, nullable=False)
    amount = db.Column(Money, nullable=False)


class BranchRecord(db.Model):
    """Ramas jurídicas: cancelación, desierto, rechazo de ofertas, excepción, convenio marco, reinicio."""
    __tablename__ = 'branch_record'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    kind = db.Column(db.String(24), nullable=False)
    state = db.Column(db.String(12), nullable=False, default='open')  # open | resolved
    reason = db.Column(db.Text, nullable=False)
    reference = db.Column(db.String(200))
    detail = db.Column(db.JSON)
    created_by = fk('user.id')
    created_at = ts()


class Subsanation(db.Model):
    __tablename__ = 'subsanation'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    offer_id = fk('offer.id')
    requirement_id = fk('spec_requirement.id', nullable=True)
    description = db.Column(db.Text, nullable=False)
    due_at = db.Column(db.DateTime, nullable=False)
    state = db.Column(db.String(12), nullable=False, default='open')  # open | answered | expired
    response_text = db.Column(db.Text)
    response_document_id = fk('document.id', nullable=True)
    responded_at = ts_null()
    requested_by = fk('user.id')
    created_at = ts()
