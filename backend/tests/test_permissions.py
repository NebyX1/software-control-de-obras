"""Permisos por acción y por recurso, competencia vigente, delegaciones y segregación de funciones."""
from datetime import datetime, timedelta, timezone
from tests.flow import Journey, key


def admin_post(api, url, json):
    r = api['administrador'].post(url, json=json)
    return r


def new_user(api, name, area_id=None):
    r = admin_post(api, '/api/v1/admin/users', {'username': f'{name}{key()[:5]}', 'email': f'{name}{key()[:5]}@tests.invalid', 'full_name': f'Usuario {name}', 'area_id': area_id})
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def login_as(app, user_json, password):
    from tests.conftest import Api
    a = Api(app)
    a._refresh()
    r = a.client.post('/api/v1/auth/login', json={'email': user_json['user']['email'], 'password': password}, headers={'X-CSRF-Token': a.csrf})
    assert r.status_code == 200, r.get_json()
    a.csrf = r.get_json()['csrf_token']
    return a


def assign(api, user, role, **kw):
    r = admin_post(api, f'/api/v1/admin/users/{user["user"]["id"]}/assignments', {'role': role, **kw})
    return r


def test_auditor_is_read_only(app, api, world):
    j = Journey(app, api, world)
    j.create()
    assert api['auditor'].get(f'/api/v1/cases/{j.code}').status_code == 200
    for name in ('request.submit', 'request.receive', 'availability.register', 'award.register'):
        assert api['auditor'].post(f'/api/v1/cases/{j.code}/actions/{name}', json={}).status_code == 403
    assert api['auditor'].post('/api/v1/cases', json={}).status_code == 403
    assert api['auditor'].post('/api/v1/suppliers', json={'name': 'x'}).status_code == 403


def test_technical_admin_has_no_procurement_competence(app, api, world):
    j = Journey(app, api, world)
    j.create()
    assert api['administrador'].get(f'/api/v1/cases/{j.code}').status_code == 404
    for name in ('request.submit', 'call.authorize', 'award.register', 'payment.authorize'):
        assert api['administrador'].post(f'/api/v1/cases/{j.code}/actions/{name}', json={}).status_code == 404


def test_frontend_cannot_grant_itself_a_role_or_admin_rights(app, api, world):
    assert api['solicitante'].post('/api/v1/admin/users', json={'username': 'x', 'email': 'x@y.invalid', 'full_name': 'X X X'}).status_code == 403
    assert api['solicitante'].post(f'/api/v1/admin/users/{world["users"]["solicitante"]}/assignments', json={'role': 'ordenador', 'legal_basis': 'auto'}).status_code == 403
    me = api['solicitante'].get('/api/v1/auth/me').get_json()['user']
    assert 'award.register' not in me['permissions']
    r = api['solicitante'].post('/api/v1/auth/login', json={'email': 'solicitante@tests.invalid', 'password': 'Test-Only-Passw0rd!x', 'roles': ['ordenador']})
    assert 'ordenador' not in str(api['solicitante'].get('/api/v1/auth/me').get_json()['user']['roles'])


def test_orderer_needs_legal_basis_and_amount_cap(app, api, world):
    r = admin_post(api, '/api/v1/admin/users', {'username': f'o{key()[:6]}', 'email': f'o{key()[:6]}@tests.invalid', 'full_name': 'Ordenador sin base'})
    u = r.get_json()
    assert assign(api, u, 'ordenador').status_code == 422  # exige resolución/delegación
    j = Journey(app, api, world)
    j.create()
    j.act('solicitante', 'request.submit')
    j.act('compras', 'request.receive')
    j.act('compras', 'procedure.classify', {'procedure_type': 'licitacion_abreviada', 'reason': 'Encuadre por monto estimado.'})
    j.act('contaduria', 'availability.register', {'fiscal_year': 2026, 'item': f'It{key()[:5]}', 'funding_source': 'RG', 'total_amount': '9000000', 'credit_support_ref': 'CRED-1',
                                                  'amount': '2200000', 'availability_date': '2026-10-01', 'support_ref': 'DISP-1'})
    spec = dict(j.spec, offer_deadline=(datetime.now(timezone.utc) + timedelta(days=20)).isoformat())
    j.act('compras', 'spec.save', {'spec': spec})
    j.act('compras', 'spec.approve', {})
    pw = new_pw(api, u)
    # competencia con tope inferior al monto: rechazada
    assert assign(api, u, 'ordenador', legal_basis='Resolución 1/2026', max_amount='1000000').status_code == 201
    ord_api = login_as(app, {'user': {'email': u['user']['email']}}, pw)
    r = ord_api.post(f'/api/v1/cases/{j.code}/actions/call.authorize', json={'reference': 'R', 'reason': 'Intento sin competencia suficiente'})
    assert r.status_code == 403 and r.get_json()['code'] == 'competence'


def new_pw(api, u):
    r = api['administrador'].patch(f'/api/v1/admin/users/{u["user"]["id"]}', json={'reset_password': True})
    pw = r.get_json()['temporary_password']
    return pw


def test_delegation_expiry_and_revocation_take_effect_immediately(app, api, world):
    u = new_user(api, 'rec')
    pw = new_pw(api, u)
    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    assert assign(api, u, 'compras', valid_from=past, valid_to=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat()).status_code == 201
    a = login_as(app, u, pw)
    j = Journey(app, api, world)
    j.create()
    assert a.get(f'/api/v1/cases/{j.code}').status_code == 404  # vigencia vencida: sin permisos
    r = assign(api, u, 'compras')
    assert r.status_code == 201
    a = login_as(app, u, pw)  # el cambio de asignaciones invalida la sesión previa
    assert a.get(f'/api/v1/cases/{j.code}').status_code == 200
    aid = [x for x in r.get_json()['user']['assignments'] if not x['revoked'] and x['valid_to'] is None][0]['id']
    api['administrador'].post(f'/api/v1/admin/assignments/{aid}/revoke', json={'reason': 'Fin de la delegación'})
    assert a.get(f'/api/v1/cases/{j.code}').status_code in (401, 404)


def test_segregation_blocks_same_person_opinion_and_award(app, api, world):
    j = Journey(app, api, world)
    j.create()
    j.prepare()
    j.open_reception()
    j.receive_offers()
    j.open()
    j.record_and_review()
    j.evaluate()
    j.act('tecnica', 'evaluation.send', {'reference': 'ENV-1', 'reason': 'Se eleva la evaluación calculada.'})
    ev = j.detail('control')['evaluation']
    offer = ev['recommended_offer_id']
    u = new_user(api, 'dual')
    pw = new_pw(api, u)
    assign(api, u, 'comision')
    assign(api, u, 'ordenador', legal_basis='Resolución de delegación 7/2026')
    dual = login_as(app, u, pw)
    v = lambda: j.detail('control')['version']
    r = dual.post(f'/api/v1/cases/{j.code}/actions/opinion.register', json={'offer_id': offer, 'reference': 'DICT-DUAL', 'reason': 'Se recomienda la mejor oferta calculada.', 'expected_version': v()})
    assert r.status_code == 200, r.get_json()
    j.act('control', 'control.register', {'offer_id': offer, 'result': 'sin_observacion', 'reference': 'INT-DUAL', 'reason': 'Sin observaciones.'})
    r = dual.post(f'/api/v1/cases/{j.code}/actions/award.register', json={'offer_id': offer, 'reference': 'RES', 'reason': 'Adjudicación de prueba del mismo usuario.', 'verified': True, 'expected_version': v()})
    assert r.status_code == 403 and r.get_json()['code'] == 'segregation'


def test_user_cannot_read_other_area_even_with_id_enumeration(app, api, world):
    j = Journey(app, api, world, )
    j.create()
    for suffix in range(1, 4):
        assert api['solicitante2'].get(f'/api/v1/cases/SC-2026-{9000 + suffix}').status_code == 404
    assert api['solicitante2'].get(f'/api/v1/cases/{j.code}/events').status_code == 404
    assert api['solicitante2'].get(f'/api/v1/ai/cases/{j.code}/inconsistencies').status_code == 404


def test_requester_cannot_create_for_another_area(app, api, world):
    j = Journey(app, api, world)
    j.create(area=world['area2'], expect=403)
