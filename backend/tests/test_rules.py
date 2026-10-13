"""Topes 2026 parametrizados: pruebas de límites exactos y de un centésimo por debajo/encima de cada umbral."""
from decimal import Decimal
import pytest
from app.modules.rules.service import suggest_procedure, notice_check
from datetime import date

D = Decimal


@pytest.mark.parametrize('amount,expected', [
    ('1024000.00', 'compra_directa'), ('1024000.01', 'concurso_precios'), ('1023999.99', 'compra_directa'),
    ('1371000.00', 'concurso_precios'), ('1371000.01', 'licitacion_abreviada'), ('1370999.99', 'concurso_precios'),
    ('13705000.00', 'licitacion_abreviada'), ('13705000.01', 'licitacion_publica'), ('13704999.99', 'licitacion_abreviada'),
    ('0.01', 'compra_directa'), ('99999999.99', 'licitacion_publica'),
])
def test_procedure_thresholds(app, amount, expected):
    with app.app_context():
        assert suggest_procedure(D(amount))['suggested'] == expected


@pytest.mark.parametrize('key,amount,expected', [
    ('comision_asesora_obligatoria', '4577000.00', False), ('comision_asesora_obligatoria', '4577000.01', True),
    ('publicacion_resultados', '204800.00', False), ('publicacion_resultados', '204800.01', True),
    ('rupe_excepcion_monto', '228899.99', True), ('rupe_excepcion_monto', '228900.00', False),
    ('garantia_cumplimiento_referencia', '5481999.99', False), ('garantia_cumplimiento_referencia', '5482000.00', True),
    ('garantia_mantenimiento_referencia', '13704999.99', False), ('garantia_mantenimiento_referencia', '13705000.00', True),
])
def test_flags_use_strict_comparators(app, key, amount, expected):
    with app.app_context():
        assert suggest_procedure(D(amount))['flags'][key] is expected


def test_vista_threshold_only_for_competitive(app):
    with app.app_context():
        assert suggest_procedure(D('54820000.00'))['flags']['vista_previa'] is False
        assert suggest_procedure(D('54820000.01'))['flags']['vista_previa'] is True
        assert suggest_procedure(D('1000000.00'))['flags']['vista_previa'] is False


def test_thresholds_come_from_rule_set_not_code(app):
    with app.app_context():
        r = suggest_procedure(D('1'))
        assert r['rule_set'] == '2026-gd-v1' and r['thresholds']['compra_directa_max']['value'] == '1024000.0000'


def test_suggest_endpoint_validates_input(app, api):
    r = api['compras'].get('/api/v1/rules/suggest?amount=1.024.000,5')
    assert r.status_code == 422
    r = api['compras'].get('/api/v1/rules/suggest?amount=1024000.01')
    assert r.status_code == 200 and r.get_json()['suggested'] == 'concurso_precios'


def test_notice_check_uses_business_days_and_requires_justification(app):
    with app.app_context():
        short = notice_check('licitacion_abreviada', date(2026, 10, 12), date(2026, 10, 16))
        assert short['applies'] and not short['ok']
        assert notice_check('licitacion_abreviada', date(2026, 10, 12), date(2026, 10, 16), justification='urgencia debidamente fundada')['ok'] is False  # 4 < 5 mínimo reducido
        reduced = notice_check('licitacion_abreviada', date(2026, 10, 5), date(2026, 10, 12), justification='justificación')
        assert reduced['ok'] and reduced['have'] == 5
        assert notice_check('licitacion_abreviada', date(2026, 9, 1), date(2026, 9, 30))['ok']
        assert notice_check('compra_directa', date(2026, 10, 12), date(2026, 10, 12))['applies'] is False
