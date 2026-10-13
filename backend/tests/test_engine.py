"""Pruebas del motor determinista (sin base de datos). Fixture ficticio de 120 luminarias del informe (§15)."""
from decimal import Decimal
import copy
import pytest
from app.modules.evaluation.engine import evaluate, EngineInputError

LINES = [{'id': 1, 'position': 1, 'quantity': '120'}]
REQS = [
    {'id': 1, 'code': 'R1', 'text': 'IP66 y 14.000 lm', 'essential': True, 'kind': 'review'},
    {'id': 2, 'code': 'R2', 'text': 'Garantía mínima 24 meses', 'essential': True, 'kind': 'numeric', 'attribute': 'warranty_months', 'operator': 'gte', 'threshold': '24'},
    {'id': 3, 'code': 'R3', 'text': 'Entrega hasta 30 días', 'essential': True, 'kind': 'numeric', 'attribute': 'delivery_days', 'operator': 'lte', 'threshold': '30'},
]
CRITERIA = [
    {'code': 'price', 'name': 'Precio', 'weight': '70', 'type': 'price_ratio'},
    {'code': 'delivery', 'name': 'Entrega', 'weight': '20', 'type': 'scale', 'attribute': 'delivery_days',
     'scale': [{'min': '0', 'max': '10', 'points': '20'}, {'min': '11', 'max': '20', 'points': '10'}, {'min': '21', 'max': '30', 'points': '0'}]},
    {'code': 'warranty', 'name': 'Garantía', 'weight': '10', 'type': 'scale', 'attribute': 'warranty_months',
     'scale': [{'min': '60', 'max': None, 'points': '10'}, {'min': '36', 'max': '59', 'points': '6'}, {'min': '24', 'max': '35', 'points': '3'}]},
]


def offer(oid, name, unit, freight, days, warranty, technical='met'):
    return {'id': oid, 'name': name, 'currency': 'UYU', 'lines': [{'line_id': 1, 'unit_price': unit, 'tax_rate': '22'}],
            'freight': freight, 'freight_includes_tax': True, 'attributes': {'delivery_days': days, 'warranty_months': warranty},
            'reviews': {'1': {'result': technical}}}


def base(mode='weighted'):
    return {'mode': mode, 'currency': 'UYU', 'lines': copy.deepcopy(LINES), 'requirements': copy.deepcopy(REQS),
            'criteria': copy.deepcopy(CRITERIA) if mode == 'weighted' else [],
            'offers': [offer(1, 'Serrana', '12500', '0', 10, 60), offer(2, 'Luz del Este', '11500', '20400', 20, 36),
                       offer(3, 'Faro Económico', '10000', '36000', 15, 12, 'not_met')]}


def by_id(result, oid):
    return next(o for o in result['offers'] if o['id'] == oid)


def test_luminarias_weighted_regression():
    r = evaluate(base())
    assert by_id(r, 1)['totals']['commercial'] == '1830000.00'
    assert by_id(r, 2)['totals']['commercial'] == '1704000.00'
    assert by_id(r, 3)['totals']['commercial'] == '1500000.00'
    assert by_id(r, 1)['score_display'] == '95.18'
    assert by_id(r, 1)['score'].startswith('95.1803278688524')
    assert by_id(r, 2)['score_display'] == '86.00'
    assert by_id(r, 3)['status'] == 'excluded' and by_id(r, 3)['score'] is None
    assert r['reference_price'] == '1704000.00'
    assert r['status'] == 'recommended' and r['recommended_offer_id'] == 1


def test_luminarias_min_price_mode_second_wins():
    r = evaluate(base('min_price'))
    assert r['recommended_offer_id'] == 2
    assert by_id(r, 3)['status'] == 'excluded'


def test_excluded_offer_does_not_set_reference_price():
    r = evaluate(base())
    assert Decimal(r['reference_price']) != Decimal('1500000')


def test_weights_come_from_spec_not_hardcoded():
    inp = base()
    inp['criteria'][0]['weight'] = '50'
    inp['criteria'][1]['scale'] = [{'min': '0', 'max': '30', 'points': '0'}]
    inp['criteria'][1]['weight'] = '0'
    r = evaluate(inp)
    assert by_id(r, 2)['score'] == '56'  # 50 (precio, peso del pliego) + 0 (entrega) + 6 (garantía 36 meses)


def test_missing_review_is_pending_not_failure():
    inp = base()
    inp['offers'][0]['reviews'] = {}
    r = evaluate(inp)
    assert by_id(r, 1)['status'] == 'pending'
    assert r['status'] == 'blocked' and r['recommended_offer_id'] is None
    assert 'Pendiente de verificar' in by_id(r, 1)['pending'][0]


def test_subsanable_gap_is_pending():
    inp = base()
    inp['offers'][0]['reviews'] = {'1': {'result': 'not_met', 'treatment': 'subsanable'}}
    assert by_id(evaluate(inp), 1)['status'] == 'pending'


def test_non_subsanable_gap_excludes():
    inp = base()
    inp['offers'][0]['reviews'] = {'1': {'result': 'not_met', 'treatment': 'no_subsanable'}}
    assert by_id(evaluate(inp), 1)['status'] == 'excluded'


def test_no_offers_blocked():
    inp = base()
    inp['offers'] = []
    r = evaluate(inp)
    assert r['status'] == 'blocked' and 'No hay ofertas' in r['blocked_reasons'][0]


def test_none_admissible():
    inp = base()
    inp['offers'] = [inp['offers'][2]]
    r = evaluate(inp)
    assert r['status'] == 'blocked' and any('Ninguna oferta admisible' in b for b in r['blocked_reasons'])


def test_exact_tie_blocks_recommendation():
    inp = base('min_price')
    inp['offers'] = [offer(1, 'A', '11500', '0', 10, 36), offer(2, 'B', '11500', '0', 10, 36)]
    r = evaluate(inp)
    assert r['tie'] and r['status'] == 'blocked' and r['recommended_offer_id'] is None


def test_similarity_warning_within_five_percent():
    inp = base('min_price')
    inp['offers'] = [offer(1, 'A', '10000', '0', 10, 36), offer(2, 'B', '10500', '0', 10, 36)]
    r = evaluate(inp)
    assert r['similar'] and r['status'] == 'recommended'
    inp['offers'][1] = offer(2, 'B', '10501', '0', 10, 36)
    assert not evaluate(inp)['similar']


def test_decimal_quantity_tax_and_rounding_half_up():
    inp = {'mode': 'min_price', 'currency': 'UYU', 'lines': [{'id': 1, 'quantity': '2.5'}], 'requirements': [], 'criteria': [],
           'offers': [{'id': 1, 'name': 'A', 'lines': [{'line_id': 1, 'unit_price': '10.01', 'tax_rate': '10'}]}]}
    r = evaluate(inp)
    # 10.01 * 2.5 = 25.025 ; IVA 10 % = 2.5025 ; total 27.5275 -> 27.53
    assert r['offers'][0]['totals']['commercial'] == '27.53'


def test_prices_include_tax_and_multiple_lines():
    inp = {'mode': 'min_price', 'currency': 'UYU', 'lines': [{'id': 1, 'quantity': '1'}, {'id': 2, 'quantity': '3'}],
           'requirements': [], 'criteria': [],
           'offers': [{'id': 1, 'name': 'A', 'prices_include_tax': True,
                       'lines': [{'line_id': 1, 'unit_price': '122', 'tax_rate': '22'}, {'line_id': 2, 'unit_price': '100', 'tax_rate': '0'}]}]}
    t = evaluate(inp)['offers'][0]['totals']
    assert t['commercial'] == '422.00' and t['subtotal_net'] == '400.00' and t['tax_total'] == '22.00'


def test_missing_line_is_pending():
    inp = base('min_price')
    inp['lines'].append({'id': 2, 'position': 2, 'quantity': '1'})
    r = evaluate(inp)
    assert all(o['status'] in ('pending', 'excluded') for o in r['offers'])
    assert r['status'] == 'blocked'


def test_foreign_currency_requires_fx_in_spec():
    inp = base('min_price')
    inp['offers'] = [dict(offer(1, 'A', '100', '0', 10, 36), currency='USD')]
    assert evaluate(inp)['status'] == 'blocked'
    inp['fx'] = {'USD': {'rate': '40.00', 'date': '2026-10-01', 'source': 'BCU'}}
    r = evaluate(inp)
    assert r['status'] == 'recommended'
    t = r['offers'][0]['totals']
    assert t['commercial'] == '14640.00' and t['comparable'] == '585600.00'  # 120 u x 100 x 1.22 = 14640 USD x 40


def test_preferences_and_partial_award_are_not_automated():
    inp = base()
    inp['flags'] = {'preferences': True}
    assert evaluate(inp)['status'] == 'blocked'
    inp['flags'] = {'partial_award': True}
    assert evaluate(inp)['status'] == 'blocked'


def test_manual_criterion_requires_attributed_score():
    inp = base()
    inp['criteria'].append({'code': 'quality', 'name': 'Calidad', 'weight': '10', 'type': 'manual'})
    r = evaluate(inp)
    assert r['status'] == 'blocked'
    for o in inp['offers']:
        o['manual_scores'] = {'quality': {'points': '8', 'evaluator': 'tec1'}}
    assert evaluate(inp)['status'] == 'recommended'


def test_scale_gap_is_not_silently_zero():
    inp = base()
    inp['offers'][0]['attributes']['delivery_days'] = '10.5'
    assert by_id(evaluate(inp), 1)['status'] == 'pending'


def test_float_input_rejected():
    inp = base()
    inp['offers'][0]['lines'][0]['unit_price'] = 12500.0
    with pytest.raises(EngineInputError):
        evaluate(inp)


def test_engine_is_deterministic_and_does_not_mutate_input():
    inp = base()
    snap = copy.deepcopy(inp)
    assert evaluate(inp) == evaluate(inp)
    assert inp == snap


def test_ranking_uses_exact_score_not_rounded():
    inp = base('min_price')
    # 1000.004 vs 1000.0049: indistinguishable at 2 decimals but ranked exactly
    inp['lines'] = [{'id': 1, 'quantity': '1'}]
    inp['requirements'] = []
    inp['offers'] = [{'id': 1, 'name': 'A', 'lines': [{'line_id': 1, 'unit_price': '1000.005', 'tax_rate': '0'}]},
                     {'id': 2, 'name': 'B', 'lines': [{'line_id': 1, 'unit_price': '1000.00', 'tax_rate': '0'}]}]
    r = evaluate(inp)
    assert r['recommended_offer_id'] == 2
