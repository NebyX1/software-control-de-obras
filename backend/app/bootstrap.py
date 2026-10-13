"""Configuración base idempotente (reglas vigentes, normativa catalogada, segregación). No crea usuarios ni expedientes."""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from app.extensions import db
from app.infrastructure.models import AuditHead, SegregationRule, RuleSet, RuleParameter, NormativeSource
from app.infrastructure.audit import GENESIS
from app.modules.rules.service import PARAMS_2026

DATA = Path(__file__).resolve().parents[1] / 'data'

SEGREGATION = [
    ('opinion.register', 'award.register', 'Quien dictamina no adjudica el mismo expediente.'),
    ('control.register', 'award.register', 'El control preventivo es independiente del ordenador.'),
    ('evaluation.run', 'award.register', 'Quien calcula la evaluación no adjudica.'),
    ('request.submit', 'award.register', 'El solicitante no adjudica su propia solicitud.'),
    ('receipt.register', 'invoice.conform', 'Quien recibe no da conformidad a la factura.'),
    ('invoice.conform', 'payment.authorize', 'Conformidad y autorización del pago deben ser personas distintas.'),
    ('payment.control', 'payment.authorize', 'El control del pago es independiente de su autorización.'),
    ('payment.authorize', 'payment.record', 'Quien autoriza no registra la ejecución del pago.'),
    ('invoice.register', 'payment.authorize', 'Quien registra la factura no autoriza su pago.'),
]


def ensure_base_config():
    if not db.session.get(AuditHead, 1):
        db.session.add(AuditHead(id=1, last_id=0, last_hash=GENESIS))
    for a, b, reason in SEGREGATION:
        if not db.session.scalar(db.select(SegregationRule).where(SegregationRule.action_a == a, SegregationRule.action_b == b)):
            db.session.add(SegregationRule(action_a=a, action_b=b, reason=reason, active=True))
    rs = db.session.scalar(db.select(RuleSet).where(RuleSet.code == '2026-gd-v1'))
    if not rs:
        rs = RuleSet(code='2026-gd-v1', name='Topes de adquisiciones 2026 · gobiernos departamentales (régimen general)',
                     jurisdiction='Uruguay · gobiernos departamentales', valid_from=date(2026, 1, 1), valid_to=date(2026, 12, 31),
                     status='active', source_refs=['S02', 'S03', 'S06', 'S11', 'S12', 'S16', 'S25'],
                     validation_note=('Contrastado el 13/10/2026 con el boletín ARCE/INE "TOCAF Enero - Diciembre 2026" (30/12/2025): '
                                      'topes de compra directa departamental, concurso de precios, licitación abreviada, comisión asesora y garantías '
                                      'coinciden. Umbrales derivados (art. 50, RUPE, vista) verificados aritméticamente; requieren validación jurídica '
                                      'institucional. Topes ampliados del art. 44 NO activados.'))
        db.session.add(rs)
        db.session.flush()
        for key, value, comparator, source, note in PARAMS_2026:
            db.session.add(RuleParameter(rule_set_id=rs.id, key=key, value=Decimal(value), comparator=comparator, source_id=source, note=note))
    if db.session.scalar(db.select(db.func.count(NormativeSource.id))) == 0:
        for s in json.loads((DATA / 'normative_sources.json').read_text(encoding='utf-8')):
            db.session.add(NormativeSource(code=s['id'], organismo=s['organismo'], titulo=s['titulo'], url=s['url'],
                                           consulta=date.fromisoformat(s['consulta']), hallazgo=s['hallazgo'], tipo=s['tipo'], kind=s['kind'],
                                           scope='Lavalleja' if s['kind'] == 'antecedente_local' else 'Uruguay · régimen general',
                                           validation_status='catalogada_sin_validacion_juridica'))
    db.session.commit()
