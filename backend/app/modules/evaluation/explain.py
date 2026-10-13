"""Explicación calculada por reglas (determinista) de un resultado de evaluación. No usa el modelo de lenguaje."""
from decimal import Decimal
from app.shared.contracts import display2

MODE_TEXT = {'weighted': 'factores ponderados con las escalas publicadas en el pliego', 'min_price': 'cumplimiento de mínimos y comparación exclusiva del precio total',
             'framework': 'selección autorizada en convenio marco'}


def _money(value, ccy):
    return f'{display2(Decimal(value))} {ccy}'


def explain(result, spec_info=None):
    ccy = result['currency']
    sections = []
    head = f'Modo de evaluación: {MODE_TEXT.get(result["mode"], result["mode"])}. Moneda de comparación: {ccy}. Motor v{result["engine_version"]}.'
    sections.append({'heading': 'Resultado', 'items': [head] + (
        [f'Recomendación calculada: {next(o["name"] for o in result["offers"] if o["id"] == result["recommended_offer_id"])}.']
        if result['recommended_offer_id'] else ['No hay recomendación: ' + ' '.join(result['blocked_reasons'])])})
    calc = []
    ref = result.get('reference_price')
    for o in result['offers']:
        t = o['totals']
        base = f'{o["name"]}: importe comercial {_money(t["commercial"], t["currency"])}; comparable {_money(t["comparable"], ccy) if t["comparable"] else "no calculable"}.'
        if o['status'] == 'admissible' and o['score'] is not None:
            parts = '; '.join(f'{c["name"]} {display2(Decimal(c["points"]))} de {display2(Decimal(c["max"]))}' for c in o['criteria'])
            base += f' Puntaje {o["score_display"]} (exacto {o["score"]}): {parts}.'
        calc.append(base)
    if result['mode'] == 'weighted' and ref:
        calc.append(f'Precio de referencia: el menor importe comparable entre ofertas admisibles ({_money(ref, ccy)}); las ofertas excluidas no integran esa base.')
    sections.append({'heading': 'La cuenta se puede repetir', 'items': calc})
    excl = [f'{o["name"]}: ' + '; '.join(o['reasons']) for o in result['offers'] if o['status'] == 'excluded']
    pend = [f'{o["name"]}: ' + '; '.join(o['pending']) for o in result['offers'] if o['status'] == 'pending']
    sections.append({'heading': 'Qué quedó fuera y por qué', 'items': excl or ['No se excluyeron ofertas.']})
    if pend:
        sections.append({'heading': 'Pendiente de verificar', 'items': pend})
    notes = ['Los importes usan aritmética decimal y redondeo de mitad hacia arriba a dos decimales por renglón; la clasificación usa el valor exacto, no el redondeado para mostrar.',
             'La verificación de requisitos es atribuida a personas; la ausencia de evidencia no se trata como incumplimiento.']
    if result.get('similar'):
        notes.append('Hay ofertas similares dentro del margen del pliego: corresponde dejar constancia de la vía elegida (art. 66); el sistema no negocia ni sortea.')
    notes += result.get('warnings', [])
    sections.append({'heading': 'Supuestos y límites', 'items': notes})
    return {'title': 'Explicación calculada por reglas', 'source': 'rules', 'sections': sections}
