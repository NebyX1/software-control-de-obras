"""Proveedores, reglas versionadas, normativa, calendario e infraestructura transversal."""
from app.extensions import db
from .base import ts, ts_null, fk, Money


class Supplier(db.Model):
    __tablename__ = 'supplier'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    tax_id = db.Column(db.String(30), nullable=True, unique=True)  # RUT u otro identificador fiscal
    country = db.Column(db.String(2), nullable=False, default='UY')
    contact_email = db.Column(db.String(120))
    active = db.Column(db.Boolean, nullable=False, default=True)
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    created_by = fk('user.id', nullable=True)
    created_at = ts()


class SupplierStatus(db.Model):
    """Estados con vigencia y respaldo (RUPE, impedimentos, antecedentes). Se versiona; no se edita."""
    __tablename__ = 'supplier_status'
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = fk('supplier.id')
    kind = db.Column(db.String(20), nullable=False)  # rupe | impedimento | antecedente
    state = db.Column(db.String(40), nullable=False)  # activo | en_ingreso | impedido | sancionado ...
    valid_from = db.Column(db.Date, nullable=True)
    valid_to = db.Column(db.Date, nullable=True)
    evidence_ref = db.Column(db.String(200), nullable=False)
    document_id = fk('document.id', nullable=True)
    verified_by = fk('user.id')
    note = db.Column(db.String(500))
    created_at = ts()


class RuleSet(db.Model):
    __tablename__ = 'rule_set'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(60), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    jurisdiction = db.Column(db.String(80), nullable=False)
    valid_from = db.Column(db.Date, nullable=False)
    valid_to = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='draft')  # draft | active | retired
    source_refs = db.Column(db.JSON, nullable=False, default=list)
    validation_note = db.Column(db.String(500))
    validated_by = fk('user.id', nullable=True)
    validated_at = ts_null()
    created_at = ts()


class RuleParameter(db.Model):
    __tablename__ = 'rule_parameter'
    id = db.Column(db.Integer, primary_key=True)
    rule_set_id = fk('rule_set.id', ondelete='CASCADE')
    key = db.Column(db.String(60), nullable=False)
    value = db.Column(db.Numeric(18, 4), nullable=False)
    unit = db.Column(db.String(20), nullable=False, default='UYU')
    comparator = db.Column(db.String(12), nullable=False, default='lte')  # lte (hasta) | gt (más de) | lt | gte
    source_id = db.Column(db.String(20))
    note = db.Column(db.String(300))
    __table_args__ = (db.UniqueConstraint('rule_set_id', 'key', name='uq_rule_param'),)


class Holiday(db.Model):
    __tablename__ = 'holiday'
    day = db.Column(db.Date, primary_key=True)
    name = db.Column(db.String(120), nullable=False)


class NormativeSource(db.Model):
    __tablename__ = 'normative_source'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)  # S01..S50
    organismo = db.Column(db.String(120), nullable=False)
    titulo = db.Column(db.String(255), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    consulta = db.Column(db.Date, nullable=False)
    hallazgo = db.Column(db.Text, nullable=False)
    tipo = db.Column(db.String(40), nullable=False, default='fuente primaria')
    scope = db.Column(db.String(80), nullable=False, default='Uruguay · régimen general')
    valid_from = db.Column(db.Date, nullable=True)
    validation_status = db.Column(db.String(40), nullable=False, default='catalogada_sin_validacion_juridica')
    kind = db.Column(db.String(30), nullable=False, default='normativa')  # normativa | antecedente_local | informe_diseno


class Counter(db.Model):
    __tablename__ = 'counter'
    name = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.Integer, nullable=False, default=0)


class IdempotencyRecord(db.Model):
    __tablename__ = 'idempotency_record'
    id = db.Column(db.Integer, primary_key=True)
    actor_id = fk('user.id')
    scope = db.Column(db.String(120), nullable=False)
    key = db.Column(db.String(80), nullable=False)
    request_hash = db.Column(db.String(64), nullable=False)
    status_code = db.Column(db.Integer, nullable=False)
    response = db.Column(db.JSON, nullable=False)
    created_at = ts()
    __table_args__ = (db.UniqueConstraint('actor_id', 'scope', 'key', name='uq_idempotency'),)


class AuditEvent(db.Model):
    """Registro funcional append-only encadenado por hash. Triggers de BD bloquean UPDATE/DELETE."""
    __tablename__ = 'audit_event'
    id = db.Column(db.BigInteger().with_variant(db.Integer, 'sqlite'), primary_key=True, autoincrement=True)
    case_id = fk('procurement_case.id', nullable=True)
    actor_id = db.Column(db.Integer, nullable=True, index=True)
    actor_name = db.Column(db.String(120), nullable=False)
    role_code = db.Column(db.String(30))
    assignment_id = db.Column(db.Integer)
    action = db.Column(db.String(80), nullable=False, index=True)
    resource_type = db.Column(db.String(40), nullable=False)
    resource_id = db.Column(db.String(40))
    resource_version = db.Column(db.Integer)
    reason = db.Column(db.Text)
    reference = db.Column(db.String(200))
    details = db.Column(db.JSON, nullable=False, default=dict)
    created_at = ts()
    prev_hash = db.Column(db.String(64), nullable=False)
    hash = db.Column(db.String(64), nullable=False, unique=True)


class AuditHead(db.Model):
    __tablename__ = 'audit_head'
    id = db.Column(db.Integer, primary_key=True)
    last_id = db.Column(db.BigInteger, nullable=False, default=0)
    last_hash = db.Column(db.String(64), nullable=False)


class BackgroundTask(db.Model):
    __tablename__ = 'background_task'
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(40), nullable=False, index=True)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    dedupe_key = db.Column(db.String(120), unique=True)
    status = db.Column(db.String(12), nullable=False, default='queued', index=True)  # queued|running|succeeded|failed|dead
    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=3)
    lease_owner = db.Column(db.String(60))
    lease_until = ts_null()
    run_after = ts()
    case_id = fk('procurement_case.id', nullable=True)
    created_by = fk('user.id', nullable=True)
    last_error = db.Column(db.String(300))
    result = db.Column(db.JSON)
    created_at = ts()
    started_at = ts_null()
    finished_at = ts_null()


class AiCall(db.Model):
    """Registro técnico de llamadas al proveedor de IA: identificadores y métricas, nunca contenido completo."""
    __tablename__ = 'ai_call'
    id = db.Column(db.Integer, primary_key=True)
    user_id = fk('user.id', nullable=True)
    case_id = fk('procurement_case.id', nullable=True)
    kind = db.Column(db.String(40), nullable=False)
    model = db.Column(db.String(80))
    prompt_version = db.Column(db.String(30))
    input_hash = db.Column(db.String(64), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False)  # ok | error | invalid | blocked | skipped
    error_code = db.Column(db.String(40))
    latency_ms = db.Column(db.Integer)
    prompt_chars = db.Column(db.Integer)
    response_chars = db.Column(db.Integer)
    chunk_ids = db.Column(db.JSON)
    egress = db.Column(db.JSON)  # clasificación, minimización aplicada, política vigente
    created_at = ts()


class AiConversation(db.Model):
    __tablename__ = 'ai_conversation'
    id = db.Column(db.Integer, primary_key=True)
    user_id = fk('user.id')
    case_id = fk('procurement_case.id', nullable=True)
    scope = db.Column(db.String(20), nullable=False)  # case | normative
    created_at = ts()


class AiMessage(db.Model):
    __tablename__ = 'ai_message'
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = fk('ai_conversation.id', ondelete='CASCADE')
    role = db.Column(db.String(12), nullable=False)
    content = db.Column(db.Text, nullable=False)
    sources = db.Column(db.JSON)
    created_at = ts()


class AiDraft(db.Model):
    """Borrador asistido. No es un acto: requiere que una persona competente lo adopte en una acción propia."""
    __tablename__ = 'ai_draft'
    id = db.Column(db.Integer, primary_key=True)
    case_id = fk('procurement_case.id')
    kind = db.Column(db.String(30), nullable=False)  # explicacion | borrador_dictamen | borrador_analisis | inconsistencias
    evaluation_id = fk('evaluation.id', nullable=True)
    content = db.Column(db.Text, nullable=False)
    sources = db.Column(db.JSON)
    warnings = db.Column(db.JSON)
    model = db.Column(db.String(80))
    author_id = fk('user.id')
    created_at = ts()
