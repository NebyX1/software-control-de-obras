"""Utilidades para recorrer el flujo completo con usuarios distintos (usadas por varias suites)."""
import uuid
from datetime import timedelta, datetime, timezone
from decimal import Decimal

LIGHT_SPEC = {
    'mode': 'weighted', 'minimum_text': 'IP66, al menos 14.000 lm, garantía mínima de 24 meses y entrega en hasta 30 días corridos.',
    'currency': 'UYU', 'reception_channel': 'presencial', 'reception_place': 'Mesa de entradas',
    'requirements': [
        {'code': 'R1', 'text': 'IP66 y al menos 14.000 lm', 'essential': True, 'kind': 'review'},
        {'code': 'R2', 'text': 'Garantía mínima de 24 meses', 'essential': True, 'kind': 'numeric', 'attribute': 'warranty_months', 'operator': 'gte', 'threshold': '24'},
        {'code': 'R3', 'text': 'Entrega hasta 30 días', 'essential': True, 'kind': 'numeric', 'attribute': 'delivery_days', 'operator': 'lte', 'threshold': '30'}],
    'criteria': [
        {'code': 'price', 'name': 'Precio', 'weight': '70', 'type': 'price_ratio'},
        {'code': 'delivery', 'name': 'Entrega', 'weight': '20', 'type': 'scale', 'attribute': 'delivery_days',
         'scale': [{'min': '0', 'max': '10', 'points': '20'}, {'min': '11', 'max': '20', 'points': '10'}, {'min': '21', 'max': '30', 'points': '0'}]},
        {'code': 'warranty', 'name': 'Garantía', 'weight': '10', 'type': 'scale', 'attribute': 'warranty_months',
         'scale': [{'min': '60', 'max': None, 'points': '10'}, {'min': '36', 'max': '59', 'points': '6'}, {'min': '24', 'max': '35', 'points': '3'}]}],
}
OFFERS = [('Serrana Iluminación', '12500', '0', 10, 60, 'met'), ('Luz del Este', '11500', '20400', 20, 36, 'met'), ('Faro Económico', '10000', '36000', 15, 12, 'not_met')]


def key():
    return uuid.uuid4().hex


class Journey:
    def __init__(self, app, api, world, estimated='2200000', spec=None, qty='120', mode_spec=None):
        self.app, self.api, self.world = app, api, world
        self.estimated, self.qty = estimated, qty
        self.spec = spec or LIGHT_SPEC
        self.code = None
        self.suppliers, self.offers = [], {}

    # ---- helpers
    def act(self, role, name, data=None, expect=200, version=True, idem=None):
        data = dict(data or {})
        if version and self.code:
            data['expected_version'] = self.detail(role)['version']
        r = self.api[role].post(f'/api/v1/cases/{self.code}/actions/{name}', json=data, headers={'Idempotency-Key': idem} if idem else {})
        assert r.status_code == expect, f'{name} -> {r.status_code} {r.get_json()}'
        return r.get_json()

    def detail(self, role='compras'):
        r = self.api[role].get(f'/api/v1/cases/{self.code}')
        assert r.status_code == 200, r.get_json()
        return r.get_json()

    def create(self, title='120 luminarias LED para barrios', role='solicitante', area=None, expect=201):
        body = {'title': title, 'area_id': area or self.world['area1'], 'need_text': 'Reposición de luminarias de alumbrado público en barrios.', 'delivery_place': 'Depósito departamental, Minas',
                'estimated_total': self.estimated, 'currency': 'UYU', 'lines': [{'description': 'Luminaria LED 150 W', 'quantity': self.qty, 'unit': 'unidades'}], 'spec': self.spec}
        r = self.api[role].post('/api/v1/cases', json=body, headers={'Idempotency-Key': key()})
        assert r.status_code == expect, r.get_json()
        if expect == 201:
            self.code = r.get_json()['code']
        return r.get_json()

    def supplier(self, name, rupe=True):
        r = self.api['compras'].post('/api/v1/suppliers', json={'name': f'{name} {key()[:6]}', 'tax_id': f'T{key()[:10]}'})
        assert r.status_code == 201, r.get_json()
        s = r.get_json()
        if rupe:
            r2 = self.api['compras'].post(f'/api/v1/suppliers/{s["id"]}/status', json={'kind': 'rupe', 'state': 'activo', 'evidence_ref': 'RUPE-CONSTANCIA-TEST'})
            assert r2.status_code == 201, r2.get_json()
        return s

    def expire_deadline(self):
        from app.extensions import db
        from sqlalchemy import text
        with self.app.app_context():
            db.session.execute(text('UPDATE spec_version SET offer_deadline = UTC_TIMESTAMP(6) - INTERVAL 1 MINUTE WHERE case_id = (SELECT id FROM procurement_case WHERE code=:c)'), {'c': self.code})
            db.session.execute(text('UPDATE envelope SET deadline_at = UTC_TIMESTAMP(6) - INTERVAL 1 MINUTE WHERE case_id = (SELECT id FROM procurement_case WHERE code=:c)'), {'c': self.code})
            db.session.commit()

    # ---- etapas
    def prepare(self, deadline_days=20, availability_amount=None, procedure='licitacion_abreviada'):
        self.act('solicitante', 'request.submit')
        self.act('compras', 'request.receive')
        self.act('compras', 'procedure.classify', {'procedure_type': procedure, 'reason': 'Encuadre acorde a la orientación por monto.'})
        self.act('contaduria', 'availability.register', {
            'fiscal_year': 2026, 'item': f'Alumbrado {key()[:6]}', 'funding_source': 'Rentas generales', 'total_amount': '9000000', 'credit_support_ref': 'CRED-TEST-1',
            'amount': availability_amount or self.estimated, 'availability_date': '2026-10-01', 'support_ref': 'DISP-TEST-42'})
        spec = dict(self.spec)
        spec['offer_deadline'] = (datetime.now(timezone.utc) + timedelta(days=deadline_days)).isoformat()
        if procedure != 'convenio_marco':
            self.act('compras', 'spec.save', {'spec': spec})
        self.act('compras', 'spec.approve', {})
        self.act('ordenador', 'call.authorize', {'reference': 'RES-LLAMADO-TEST', 'reason': 'Se autoriza el llamado según pliego aprobado.'})

    def open_reception(self):
        pub = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
        self.act('compras', 'publicity.register', {'kind': 'convocatoria', 'state': 'external_constancia', 'reference': 'ARCE-PUB-TEST', 'published_on': pub})
        assert self.detail()['status'] == 'receiving_offers'

    def receive_offers(self, offers=OFFERS, with_documents=True):
        d = self.detail()
        for name, unit, freight, days, warranty, tech in offers:
            s = self.supplier(name)
            self.suppliers.append(s)
            r = self.act('recepcion', 'envelope.register', {'supplier_id': s['id'], 'channel': 'presencial', 'custody_note': 'Recibido en mesa de entradas y custodiado en caja fuerte.'})
        envs = self.detail('recepcion')['envelopes']
        if with_documents:
            for env in envs:
                r = self.api['recepcion'].upload(f'/api/v1/cases/{self.code}/documents', {'kind': 'oferta', 'title': f'Oferta {env["receipt_code"]}', 'classification': 'internal', 'envelope_id': str(env['id'])},
                                                 'oferta.txt', f'Oferta de {env["supplier"]}. Garantía 36 meses. Entrega en 20 días. Precio unitario 11500 IVA no incluido.'.encode())
                assert r.status_code == 201, r.get_json()
        return envs

    def open(self):
        self.expire_deadline()
        self.act('compras', 'opening.perform', {'reference': 'ACTA-TEST-1', 'participants': 'Compras - Responsable\nRecepción - Testigo'})
        d = self.detail()
        assert d['status'] == 'offers_opened'
        return d

    def record_and_review(self, offers=OFFERS):
        d = self.detail('tecnica')
        line_id = d['lines'][0]['id']
        req = next(r for r in d['spec']['requirements'] if r['kind'] == 'review')
        by_name = {o['supplier'].rsplit(' ', 1)[0]: o for o in d['offers']}
        for name, unit, freight, days, warranty, tech in offers:
            o = by_name[name]
            self.act('tecnica', 'offer.record', {'offer_id': o['id'], 'lines': [{'request_line_id': line_id, 'unit_price': unit, 'tax_rate': '22'}], 'freight': freight,
                                                  'freight_includes_tax': True, 'delivery_days': days, 'warranty_months': warranty, 'reason': 'Datos validados desde la ficha técnica p. 2-3.'})
            self.act('tecnica', 'requirement.review', {'offer_id': o['id'], 'requirement_id': req['id'], 'result': tech, 'treatment': 'no_subsanable' if tech == 'not_met' else None,
                                                       'note': 'Ficha técnica página 2.' if tech == 'met' else 'No acredita IP66 en la ficha técnica.'})
        return by_name

    def evaluate(self):
        self.act('tecnica', 'evaluation.run', {})
        return self.detail('tecnica')['evaluation']

    def decide(self, offer_id=None):
        self.act('tecnica', 'evaluation.send', {'reference': 'ENV-TEST-1', 'reason': 'Se eleva la comparación calculada.'})
        ev = self.detail('control')['evaluation']
        offer = offer_id or ev['recommended_offer_id']
        self.act('comision', 'opinion.register', {'offer_id': offer, 'reference': 'DICT-TEST-1', 'reason': 'Se recomienda la oferta mejor evaluada conforme al pliego.'})
        self.act('control', 'control.register', {'offer_id': offer, 'result': 'sin_observacion', 'reference': 'INT-TEST-1', 'reason': 'Gasto sin observaciones.'})
        self.act('ordenador', 'award.register', {'offer_id': offer, 'reference': 'RES-ADJ-TEST-1', 'reason': 'Se adjudica la oferta más conveniente.', 'verified': True})
        return offer

    def post_award(self):
        self.act('compras', 'communication.register', {'kind': 'notificacion', 'state': 'external_constancia', 'reference': 'NOTIF-TEST-1'})
        self.act('compras', 'communication.register', {'kind': 'publicacion', 'state': 'external_constancia', 'reference': 'PUB-ADJ-TEST-1'})
        self.act('compras', 'contract.register', {'status': 'not_required', 'reason_not_required': 'Compra por orden sin contrato formal según pliego.'})
        self.act('compras', 'order.issue', {'confirm': True})

    def full_to_order(self):
        self.create()
        self.prepare()
        self.open_reception()
        self.receive_offers()
        self.open()
        self.record_and_review()
        self.evaluate()
        self.decide()
        self.post_award()
        return self.detail()
