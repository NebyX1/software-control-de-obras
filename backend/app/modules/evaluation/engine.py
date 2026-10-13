"""Motor de evaluación determinista y versionado.

Puro: no accede a la base, a la red ni al modelo de lenguaje. Recibe entradas exactas (pliego + datos validados de
ofertas) y devuelve un resultado reproducible. Importes con Decimal; el puntaje se conserva sin redondear y solo se
redondea para mostrar. No ejecuta código ni expresiones suministradas por usuarios o documentos.
"""
from decimal import Decimal, InvalidOperation
from app.shared.contracts import money, dstr, display2

ENGINE_VERSION = '1.0.0'
MODES = ('weighted', 'min_price', 'framework')
OPERATORS = {
    'gte': lambda a, b: a >= b, 'lte': lambda a, b: a <= b, 'gt': lambda a, b: a > b,
    'lt': lambda a, b: a < b, 'eq': lambda a, b: a == b,
}
OPERATOR_TEXT = {'gte': 'al menos', 'lte': 'hasta', 'gt': 'más de', 'lt': 'menos de', 'eq': 'exactamente'}
HUNDRED = Decimal(100)


class EngineInputError(ValueError):
    pass


def D(value, name):
    if value is None or isinstance(value, (bool, float)):
        raise EngineInputError(f'{name}: se requiere un decimal exacto (texto o entero)')
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise EngineInputError(f'{name}: número inválido')
    if not d.is_finite():
        raise EngineInputError(f'{name}: número inválido')
    return d


def _line_total(line, req_qty, prices_include_tax):
    price = D(line['unit_price'], 'unit_price')
    rate = D(line.get('tax_rate', 0), 'tax_rate')
    discount = D(line.get('discount', 0), 'discount')
    if prices_include_tax:
        gross = price * req_qty - discount
        net = gross / (1 + rate / HUNDRED)
        return money(gross), money(net), money(gross - net)
    net = price * req_qty - discount
    tax = net * rate / HUNDRED
    return money(net + tax), money(net), money(tax)


def offer_totals(offer, lines, currency, fx):
    """Devuelve (totales, pendientes). Separa importe comercial, comparable y adjudicable/pagadero."""
    pending = []
    by_line = {str(l['line_id']): l for l in offer.get('lines', [])}
    include = bool(offer.get('prices_include_tax', False))
    detail, subtotal, tax_total, lines_total = [], Decimal(0), Decimal(0), Decimal(0)
    for req_line in lines:
        q = D(req_line['quantity'], 'quantity')
        quoted = by_line.get(str(req_line['id']))
        if quoted is None:
            pending.append(f'Falta el precio del renglón {req_line.get("position", req_line["id"])}.')
            continue
        if quoted.get('quantity') is not None and D(quoted['quantity'], 'quantity') != q:
            pending.append(f'La cantidad ofrecida del renglón {req_line.get("position", req_line["id"])} difiere de la solicitada; requiere revisión (adjudicación parcial no automatizada).')
        total, net, tax = _line_total(quoted, q, include)
        lines_total += total
        subtotal += net
        tax_total += tax
        detail.append({'line_id': req_line['id'], 'quantity': dstr(q), 'unit_price': dstr(D(quoted['unit_price'], 'unit_price')),
                       'net': dstr(net), 'tax': dstr(tax), 'total': dstr(total)})
    freight = D(offer.get('freight', 0), 'freight')
    freight_total = money(freight if offer.get('freight_includes_tax', True) else freight * (1 + D(offer.get('freight_tax_rate', 0), 'freight_tax_rate') / HUNDRED))
    discount_total = D(offer.get('discount_total', 0), 'discount_total')
    commercial = money(lines_total + freight_total - discount_total)
    offer_ccy = offer.get('currency') or currency
    rate = Decimal(1)
    if offer_ccy != currency:
        entry = (fx or {}).get(offer_ccy)
        if not entry or not entry.get('rate'):
            pending.append(f'Moneda {offer_ccy} sin tipo de cambio fijado en el pliego (fecha y fuente); conversión no automatizada.')
            rate = None
        else:
            rate = D(entry['rate'], 'fx.rate')
    comparable = money(commercial * rate) if rate is not None else None
    return {
        'currency': offer_ccy, 'evaluation_currency': currency, 'subtotal_net': dstr(subtotal), 'tax_total': dstr(tax_total),
        'freight': dstr(freight_total), 'discount': dstr(discount_total),
        'commercial': dstr(commercial), 'comparable': dstr(comparable) if comparable is not None else None,
        'awardable': dstr(commercial), 'fx_rate': dstr(rate) if rate is not None else None, 'lines': detail,
    }, pending


def requirement_result(req, offer):
    """Distingue cumple / no cumple / pendiente. La ausencia de evidencia nunca es incumplimiento."""
    if req.get('kind') == 'numeric':
        value = (offer.get('attributes') or {}).get(req.get('attribute'))
        if value is None:
            return {'result': 'pending', 'observed': None, 'treatment': None}
        op = OPERATORS.get(req.get('operator'))
        if not op:
            raise EngineInputError(f'Operador desconocido: {req.get("operator")}')
        ok = op(D(value, req['attribute']), D(req['threshold'], 'threshold'))
        return {'result': 'met' if ok else 'not_met', 'observed': dstr(D(value, req['attribute'])), 'treatment': None}
    review = (offer.get('reviews') or {}).get(str(req['id']))
    if not review or review.get('result') not in ('met', 'not_met'):
        return {'result': 'pending', 'observed': review.get('observed') if review else None, 'treatment': None}
    return {'result': review['result'], 'observed': review.get('observed'), 'treatment': review.get('treatment')}


def scale_points(criterion, value):
    for band in criterion.get('scale') or []:
        lo = None if band.get('min') is None else D(band['min'], 'scale.min')
        hi = None if band.get('max') is None else D(band['max'], 'scale.max')
        if (lo is None or value >= lo) and (hi is None or value <= hi):
            return D(band['points'], 'scale.points')
    return None


def validate_criteria(mode, criteria):
    if mode == 'weighted':
        if not criteria:
            raise EngineInputError('El modo ponderado requiere criterios con pesos y escalas publicadas en el pliego.')
        total = sum(D(c['weight'], 'weight') for c in criteria)
        if total <= 0:
            raise EngineInputError('La suma de pesos debe ser positiva.')
        for c in criteria:
            if c['type'] not in ('price_ratio', 'scale', 'manual'):
                raise EngineInputError(f'Tipo de criterio no soportado: {c["type"]}')
            if c['type'] == 'scale' and not c.get('scale'):
                raise EngineInputError(f'El criterio {c["code"]} requiere una escala publicada.')


def evaluate(inp):
    mode = inp['mode']
    if mode not in MODES:
        raise EngineInputError(f'Modo de evaluación desconocido: {mode}')
    currency = inp.get('currency', 'UYU')
    fx = inp.get('fx') or {}
    margin = D(inp.get('similarity_margin', '0.05'), 'similarity_margin')
    lines, requirements, criteria = inp.get('lines', []), inp.get('requirements', []), inp.get('criteria', [])
    flags = inp.get('flags') or {}
    validate_criteria(mode, criteria)
    blocked, warnings = [], []
    if flags.get('preferences'):
        blocked.append('El pliego declara preferencias o un régimen especial: la regla no está parametrizada; se requiere revisión documental competente.')
    if flags.get('partial_award'):
        blocked.append('El pliego admite adjudicación parcial por renglón: no está automatizada; se requiere revisión documental competente.')
    if mode == 'weighted':
        total_w = sum(D(c['weight'], 'weight') for c in criteria)
        if total_w != HUNDRED:
            warnings.append(f'Los pesos del pliego suman {dstr(total_w)} (no 100): el puntaje máximo es {dstr(total_w)}.')

    rows = []
    for offer in inp.get('offers', []):
        totals, pending = offer_totals(offer, lines, currency, fx)
        exclusions, o_warnings, req_rows = [], [], []
        terms = inp.get('delivery_terms')
        if terms and offer.get('delivery_terms') and offer['delivery_terms'] != terms:
            pending.append(f'Condición de entrega distinta ({offer["delivery_terms"]} vs {terms}); normalizar antes de comparar.')
        for req in requirements:
            res = requirement_result(req, offer)
            label = f'{req["code"]}: {req["text"]}'
            req_rows.append({'id': req['id'], 'code': req['code'], 'text': req['text'], 'essential': bool(req.get('essential', True)),
                             'kind': req.get('kind', 'review'), **res})
            if res['result'] == 'not_met':
                if not req.get('essential', True):
                    o_warnings.append(f'No cumple (no esencial): {label}')
                elif res['treatment'] == 'subsanable':
                    pending.append(f'Carencia subsanable pendiente: {label}')
                else:
                    exclusions.append(f'No cumple: {label}')
            elif res['result'] == 'pending' and req.get('essential', True):
                pending.append(f'Pendiente de verificar: {label}')
        status = 'excluded' if exclusions else ('pending' if pending else 'admissible')
        rows.append({'id': offer['id'], 'name': offer.get('name', str(offer['id'])), 'status': status, 'reasons': exclusions,
                     'pending': pending, 'warnings': o_warnings, 'requirements': req_rows, 'totals': totals,
                     'criteria': [], 'score': None, 'score_display': None, 'rank': None, '_comparable': totals['comparable'],
                     '_offer': offer})

    admissible = [r for r in rows if r['status'] == 'admissible' and r['_comparable'] is not None]
    reference = min((Decimal(r['_comparable']) for r in admissible), default=None)
    scored = []
    for r in admissible:
        comp = Decimal(r['_comparable'])
        points, row_pending = [], []
        if mode == 'weighted':
            for c in criteria:
                weight = D(c['weight'], 'weight')
                if c['type'] == 'price_ratio':
                    p = weight * reference / comp
                elif c['type'] == 'scale':
                    value = (r['_offer'].get('attributes') or {}).get(c['attribute'])
                    if value is None:
                        row_pending.append(f'Falta el dato "{c["name"]}" necesario para la escala publicada.')
                        continue
                    p = scale_points(c, D(value, c['attribute']))
                    if p is None:
                        row_pending.append(f'El valor {value} de "{c["name"]}" no está cubierto por la escala publicada en el pliego.')
                        continue
                else:
                    manual = (r['_offer'].get('manual_scores') or {}).get(c['code'])
                    if not manual or manual.get('points') is None or not manual.get('evaluator'):
                        row_pending.append(f'Falta la evaluación atribuida del criterio cualitativo "{c["name"]}".')
                        continue
                    p = D(manual['points'], 'manual.points')
                    if p < 0 or p > weight:
                        row_pending.append(f'Puntaje del criterio "{c["name"]}" fuera de su escala (0 a {dstr(weight)}).')
                        continue
                points.append({'code': c['code'], 'name': c['name'], 'max': dstr(weight), 'points': dstr(p)})
            score = sum((Decimal(x['points']) for x in points), Decimal(0))
        else:
            score = HUNDRED * reference / comp
            points = [{'code': 'price', 'name': 'Precio (índice base 100; el orden es por importe)', 'max': '100', 'points': dstr(score)}]
        if row_pending:
            r['status'] = 'pending'
            r['pending'].extend(row_pending)
            continue
        r['criteria'], r['score'], r['score_display'] = points, dstr(score), display2(score)
        scored.append((r, score, comp))

    for r in rows:
        if r['status'] == 'pending':
            r['score'] = r['score_display'] = None
    pending_offers = [r for r in rows if r['status'] == 'pending']
    rows_adm = [t for t in scored if t[0]['status'] == 'admissible']
    if mode == 'weighted':
        ranked = sorted(rows_adm, key=lambda t: (-t[1], t[2]))
        keyf = lambda t: t[1]
    else:
        ranked = sorted(rows_adm, key=lambda t: t[2])
        keyf = lambda t: t[2]
    tie = len(ranked) > 1 and keyf(ranked[0]) == keyf(ranked[1])
    similar = False
    if len(ranked) > 1 and not tie:
        a, b = keyf(ranked[0]), keyf(ranked[1])
        similar = ((a - b) / a <= margin) if mode == 'weighted' else ((b - a) / a <= margin)
    for i, t in enumerate(ranked, 1):
        t[0]['rank'] = i

    if not rows:
        blocked.append('No hay ofertas para evaluar: el ordenador debe resolver el curso del procedimiento (desierto, nueva convocatoria u otra vía).')
    if mode == 'framework' and len(rows) != 1:
        blocked.append('Convenio marco: debe registrarse una única selección autorizada.')
    if pending_offers:
        blocked.append('Hay ofertas con datos críticos pendientes de verificar; no se recomienda hasta completarlos: ' + '; '.join(
            f'{r["name"]} ({len(r["pending"])})' for r in pending_offers) + '.')
    if rows and not ranked and not pending_offers:
        blocked.append('Ninguna oferta admisible: no se recomienda adjudicar.')
    if tie:
        blocked.append('Empate exacto: se requiere una vía jurídica fundada; el sistema no sortea ni desempata.')
    status = 'blocked' if blocked else 'recommended'
    for r in rows:
        r.pop('_offer')
        r.pop('_comparable')
    return {
        'engine_version': ENGINE_VERSION, 'mode': mode, 'currency': currency, 'status': status,
        'blocked_reasons': blocked, 'warnings': warnings,
        'recommended_offer_id': ranked[0][0]['id'] if status == 'recommended' and ranked else None,
        'reference_price': dstr(reference) if reference is not None else None,
        'tie': tie, 'similar': similar and not tie, 'similarity_margin': dstr(margin),
        'offers': sorted(rows, key=lambda r: (r['rank'] is None, r['rank'] or 0, str(r['id']))),
    }
