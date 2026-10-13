"""Recorrido completo con usuarios distintos, motor real y reglas de bloqueo."""
from decimal import Decimal
from tests.flow import Journey, key


def test_full_journey_luminarias(app, api, world):
    j = Journey(app, api, world)
    j.full_to_order()
    d = j.detail()
    assert d['status'] == 'ordered' and d['stage'] == 5
    ev = d['evaluation']['result']
    by = {o['name'].rsplit(' ', 1)[0]: o for o in ev['offers']}
    assert by['Serrana Iluminación']['score_display'] == '95.18'
    assert by['Luz del Este']['score_display'] == '86.00'
    assert by['Faro Económico']['status'] == 'excluded'
    assert ev['reference_price'] == '1704000.00'
    assert d['award']['amount'] == '1830000.00'
    order = d['order']
    line = order['lines'][0]
    # entregas parciales
    j.act('recepcion', 'receipt.register', {'reference': 'REM-1', 'lines': [{'order_line_id': line['id'], 'accepted_qty': '60', 'rejected_qty': '0'}]})
    j.act('contaduria', 'invoice.register', {'doc_type': 'e-Factura', 'series': 'A', 'number': '100', 'issue_date': '2026-10-13', 'lines': [{'order_line_id': line['id'], 'quantity': '60'}]})
    d = j.detail('contaduria')
    assert d['status'] == 'invoicing' and d['stage'] == 6
    inv = d['invoices'][0]
    assert inv['total'] == '915000.00'  # el valor recibido habilita 915.000, no el total contratado
    j.act('contaduria', 'invoice.conform', {'invoice_id': inv['id'], 'reference': 'CONF-1', 'reason': 'Conciliada con la recepción.'})
    j.act('control', 'payment.control', {'invoice_id': inv['id'], 'result': 'sin_observacion', 'reference': 'CTRL-PAGO-1', 'reason': 'Pago sin observaciones.'})
    j.act('ordenador', 'payment.authorize', {'invoice_id': inv['id'], 'amount': '915000', 'reference': 'AUT-PAGO-1', 'reason': 'Se autoriza el pago.'})
    j.act('tesoreria', 'payment.record', {'invoice_id': inv['id'], 'amount': '915000', 'proof_reference': 'COMP-1', 'executed_on': '2026-10-13', 'payment_key': key()})
    j.act('recepcion', 'receipt.register', {'reference': 'REM-2', 'lines': [{'order_line_id': line['id'], 'accepted_qty': '60'}]})
    j.act('contaduria', 'invoice.register', {'doc_type': 'e-Factura', 'series': 'A', 'number': '101', 'issue_date': '2026-10-13', 'lines': [{'order_line_id': line['id'], 'quantity': '60'}]})
    inv2 = [i for i in j.detail('contaduria')['invoices'] if i['number'] == '101'][0]
    j.act('contaduria', 'invoice.conform', {'invoice_id': inv2['id'], 'reference': 'CONF-2', 'reason': 'Conciliada.'})
    j.act('control', 'payment.control', {'invoice_id': inv2['id'], 'result': 'sin_observacion', 'reference': 'CTRL-PAGO-2', 'reason': 'Sin observaciones.'})
    j.act('ordenador', 'payment.authorize', {'invoice_id': inv2['id'], 'amount': '915000', 'reference': 'AUT-PAGO-2', 'reason': 'Autorizado.'})
    j.act('tesoreria', 'payment.record', {'invoice_id': inv2['id'], 'amount': '915000', 'proof_reference': 'COMP-2', 'executed_on': '2026-10-13', 'payment_key': key()})
    j.act('compras', 'case.close', {'reference': 'CIERRE-1', 'reason': 'Recepción total y pagos conciliados.'})
    d = j.detail()
    assert d['status'] == 'closed' and d['stage'] == 7 and d['closure']
    # la auditoría registra actores reales
    ev_ = api['auditor'].get(f'/api/v1/audit?case={j.code}&per_page=100').get_json()
    actors = {e['actor'] for e in ev_['items']}
    assert len(actors) >= 8
    assert api['auditor'].get('/api/v1/audit/verify').get_json()['ok'] is True


def test_actions_only_for_authorized_roles(app, api, world):
    j = Journey(app, api, world)
    j.create()
    j.act('solicitante', 'request.submit')
    j.act('solicitante', 'request.receive', expect=403)
    j.act('compras', 'request.receive')
    j.act('compras', 'call.authorize', {'reference': 'X', 'reason': 'Sin competencia'}, expect=403)
    j.act('compras', 'award.register', {}, expect=403)


def test_stage_is_server_owned_and_client_cannot_set_it(app, api, world):
    j = Journey(app, api, world)
    j.create()
    r = api['solicitante'].post(f'/api/v1/cases/{j.code}/actions/request.submit', json={'stage': 7, 'status': 'closed', 'expected_version': 1})
    assert r.status_code == 200
    d = j.detail()
    assert d['status'] == 'submitted' and d['stage'] == 0


def test_blockers_are_explained_not_internal_errors(app, api, world):
    j = Journey(app, api, world)
    j.create()
    j.act('solicitante', 'request.submit')
    j.act('compras', 'request.receive')
    r = j.act('ordenador', 'call.authorize', {'reference': 'R', 'reason': 'Intento sin disponibilidad ni pliego aprobado'}, expect=422)
    assert r['code'] == 'blocked' and any('disponibilidad' in b.lower() for b in r['blockers'])
    d = j.detail('compras')
    assert d['next']['label'] and d['next']['responsible']


def test_version_conflict_returns_recoverable_409(app, api, world):
    j = Journey(app, api, world)
    j.create()
    r = api['solicitante'].post(f'/api/v1/cases/{j.code}/actions/request.submit', json={'expected_version': 99})
    assert r.status_code == 409 and r.get_json()['code'] == 'version_conflict' and r.get_json()['current_version'] == 1


def test_other_area_cannot_open_case_by_id(app, api, world):
    j = Journey(app, api, world)
    j.create()
    assert api['solicitante2'].get(f'/api/v1/cases/{j.code}').status_code == 404
    assert api['solicitante2'].post(f'/api/v1/cases/{j.code}/actions/request.submit', json={}).status_code == 404
    listing = api['solicitante2'].get('/api/v1/cases?per_page=100').get_json()
    assert j.code not in {c['code'] for c in listing['items']}
