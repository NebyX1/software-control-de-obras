"""Reglas versionadas: topes, vigencias, ámbito y calendario. Los valores salen de `rule_set/rule_parameter`, no del código."""
from datetime import date, timedelta
from decimal import Decimal
from app.extensions import db
from app.infrastructure.models import RuleSet, RuleParameter, Holiday
from app.shared.contracts import dstr
from app.shared.errors import ApiError

PROCEDURE_LABELS = {
    'compra_directa': 'Compra directa', 'concurso_precios': 'Concurso de precios', 'licitacion_abreviada': 'Licitación abreviada',
    'licitacion_publica': 'Licitación pública', 'convenio_marco': 'Convenio marco', 'excepcion': 'Compra directa por excepción',
}
COMPETITIVE = {'concurso_precios', 'licitacion_abreviada', 'licitacion_publica'}

# Definición de los parámetros del régimen general 2026 para gobiernos departamentales (ver docs/REGLAS_VIGENCIAS.md)
PARAMS_2026 = [
    ('compra_directa_max', '1024000', 'lte', 'S02', 'Compra directa común, gobiernos departamentales (art. 33 lit. C). Boletín ARCE/INE 2026.'),
    ('concurso_precios_max', '1371000', 'lte', 'S03', 'Máximo del concurso de precios (art. 33 lit. B).'),
    ('licitacion_abreviada_max', '13705000', 'lte', 'S03', 'Máximo de licitación abreviada (art. 33 lit. A).'),
    ('comision_asesora_min', '4577000', 'gt', 'S11', 'Intervención obligatoria de la Comisión Asesora en procedimientos competitivos (art. 66).'),
    ('publicacion_resultados_min', '204800', 'gt', 'S06', '20 % del máximo departamental de compra directa (art. 50). Derivado: validar jurídicamente.'),
    ('rupe_excepcion_max', '228900', 'lt', 'S16', '35 % del tope común de $ 654.000 (Decreto 202/024). Derivado: validar jurídicamente.'),
    ('vista_min', '54820000', 'gt', 'S12', 'Cuatro veces el máximo de licitación abreviada (art. 67). Derivado: validar jurídicamente.'),
    ('garantia_mantenimiento_ref', '13705000', 'gte', 'S25', 'Referencia art. 64: revisar pliego y excepciones.'),
    ('fiel_cumplimiento_ref', '5482000', 'gte', 'S25', 'Referencia art. 64: revisar opciones y excepciones.'),
]


def active_rule_set(at=None):
    at = at or date.today()
    q = (db.select(RuleSet).where(RuleSet.status == 'active', RuleSet.valid_from <= at)
         .where((RuleSet.valid_to.is_(None)) | (RuleSet.valid_to >= at)).order_by(RuleSet.valid_from.desc()))
    return db.session.scalars(q).first()


def parameters(rule_set):
    rows = db.session.scalars(db.select(RuleParameter).where(RuleParameter.rule_set_id == rule_set.id)).all()
    return {r.key: r for r in rows}


def compare(value, comparator, threshold):
    value, threshold = Decimal(value), Decimal(threshold)
    return {'lte': value <= threshold, 'lt': value < threshold, 'gt': value > threshold, 'gte': value >= threshold}[comparator]


def suggest_procedure(amount, at=None):
    """Orientación por monto con IVA. Respeta 'hasta' y 'más de': $ 1.024.000 y $ 1.024.000,01 dan resultados distintos."""
    rs = active_rule_set(at)
    if not rs:
        raise ApiError('no_rule_set', 'No hay un conjunto de reglas vigente y validado. Un administrador debe activarlo.', 409)
    p = parameters(rs)
    amount = Decimal(amount)
    for key, ptype in (('compra_directa_max', 'compra_directa'), ('concurso_precios_max', 'concurso_precios'),
                       ('licitacion_abreviada_max', 'licitacion_abreviada')):
        if compare(amount, p[key].comparator, p[key].value):
            suggested = ptype
            break
    else:
        suggested = 'licitacion_publica'
    flags = {
        'comision_asesora_obligatoria': suggested in COMPETITIVE and compare(amount, p['comision_asesora_min'].comparator, p['comision_asesora_min'].value),
        'publicacion_resultados': compare(amount, p['publicacion_resultados_min'].comparator, p['publicacion_resultados_min'].value),
        'rupe_excepcion_monto': compare(amount, p['rupe_excepcion_max'].comparator, p['rupe_excepcion_max'].value),
        'vista_previa': suggested in COMPETITIVE and compare(amount, p['vista_min'].comparator, p['vista_min'].value),
        'garantia_mantenimiento_referencia': compare(amount, p['garantia_mantenimiento_ref'].comparator, p['garantia_mantenimiento_ref'].value),
        'garantia_cumplimiento_referencia': compare(amount, p['fiel_cumplimiento_ref'].comparator, p['fiel_cumplimiento_ref'].value),
    }
    return {
        'suggested': suggested, 'label': PROCEDURE_LABELS[suggested], 'amount': dstr(amount), 'rule_set': rs.code,
        'valid_from': rs.valid_from.isoformat(), 'flags': flags,
        'thresholds': {k: {'value': dstr(v.value), 'comparator': v.comparator, 'source': v.source_id} for k, v in p.items()},
        'notice': 'El monto orienta; el encuadre legal depende del objeto, excepciones y regímenes especiales. No se activaron los topes ampliados del art. 44.',
    }


# ----------------------------------------------------------------- calendario y plazos

def holidays():
    return {h.day for h in db.session.scalars(db.select(Holiday)).all()}


def is_business_day(d, hol):
    return d.weekday() < 5 and d not in hol


def business_days_between(start, end, hol=None):
    """Días hábiles transcurridos (excluye `start`, incluye `end`)."""
    hol = holidays() if hol is None else hol
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if is_business_day(d, hol):
            n += 1
    return n


# Referencias de antelación (informe §09, TOCAF 51/52). Son advertencias a validar, no cómputos jurídicos definitivos.
NOTICE_REFERENCE = {
    'licitacion_publica': {'unit': 'calendar', 'days': 15, 'days_foreign': 20, 'source': 'S07'},
    'concurso_precios': {'unit': 'business', 'days': 3, 'reduced': 2, 'source': 'S08'},
    'licitacion_abreviada': {'unit': 'business', 'days': 10, 'reduced': 5, 'source': 'S08'},
}


def notice_check(procedure_type, published_on, deadline_on, foreign=False, justification=None):
    ref = NOTICE_REFERENCE.get(procedure_type)
    if not ref:
        return {'applies': False, 'warnings': []}
    hol = holidays()
    if ref['unit'] == 'calendar':
        have, need = (deadline_on - published_on).days, ref['days_foreign'] if foreign else ref['days']
    else:
        have, need = business_days_between(published_on, deadline_on, hol), ref['days']
    reduced_min = ref.get('reduced')
    warnings = []
    ok = have >= need
    if not ok:
        if reduced_min and have >= reduced_min and justification:
            warnings.append(f'Antelación reducida ({have} < {need}) con justificación registrada; verificar condiciones de la reducción ({ref["source"]}).')
            ok = True
        else:
            warnings.append(f'La antelación ({have}) es menor a la de referencia ({need}). Se requiere justificación y verificación jurídica ({ref["source"]}).')
    if not hol:
        warnings.append('No hay feriados cargados en el calendario; el cómputo solo excluye sábados y domingos.')
    return {'applies': True, 'ok': ok, 'have': have, 'need': need, 'unit': ref['unit'], 'warnings': warnings}
