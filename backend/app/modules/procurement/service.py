"""Alta y edición de solicitudes, pliegos (requisitos y criterios estructurados) y utilidades del expediente."""
from datetime import datetime
from decimal import Decimal
from sqlalchemy.dialects.mysql import insert
from app.extensions import db
from app.infrastructure import audit
from app.infrastructure.models import (Area, Counter, ProcurementCase, RequestLine, SpecVersion, SpecRequirement, SpecCriterion, Supplier)
from app.modules.evaluation.engine import OPERATORS, validate_criteria, EngineInputError
from app.modules.identity.permissions import find_assignment
from app.modules.procurement import inputs as inp
from app.shared.contracts import canonical_hash, dstr, to_decimal, utcnow
from app.shared.errors import ApiError, require

ATTRIBUTES = {'delivery_days': 'Plazo de entrega (días)', 'warranty_months': 'Garantía (meses)'}
MODES = ('min_price', 'weighted', 'framework')


def next_code():
    year = datetime.now().year
    name = f'case-{year}'
    db.session.execute(insert(Counter).values(name=name, value=1).on_duplicate_key_update(value=Counter.value + 1))
    n = db.session.execute(db.select(Counter.value).where(Counter.name == name)).scalar_one()
    return f'SC-{year}-{n:04d}'


def parse_lines(data):
    rows = inp.items(data, 'lines', 'Renglones', 1, 100)
    out = []
    for i, row in enumerate(rows, 1):
        out.append({
            'position': i, 'description': inp.text(row, 'description', f'Renglón {i}: descripción', 3, 300),
            'quantity': inp.decimal(row, 'quantity', f'Renglón {i}: cantidad', places=4),
            'unit': inp.text(row, 'unit', f'Renglón {i}: unidad', 1, 30),
            'estimated_unit_price': inp.decimal(row, 'estimated_unit_price', f'Renglón {i}: precio estimado', required=False, places=4),
            'tax_rate': inp.decimal(row, 'tax_rate', f'Renglón {i}: IVA (%)', required=False, positive=False, maximum=100, places=3),
        })
    return out


def parse_requirements(items):
    out, seen = [], set()
    for i, row in enumerate(items or [], 1):
        kind = inp.choice(row, 'kind', f'Requisito {i}: tipo', ('review', 'numeric'), required=False, default='review')
        item = {'position': i, 'code': inp.text(row, 'code', f'Requisito {i}: código', 1, 20, required=False, default=f'R{i}'),
                'text': inp.text(row, 'text', f'Requisito {i}: texto', 3, 500), 'essential': inp.boolean(row, 'essential', True), 'kind': kind,
                'attribute': None, 'operator': None, 'threshold': None, 'unit': inp.text(row, 'unit', 'Unidad', 1, 20, required=False)}
        require(item['code'] not in seen, 'validation', f'Requisito {i}: el código {item["code"]} está repetido.', 422)
        seen.add(item['code'])
        if kind == 'numeric':
            item['attribute'] = inp.choice(row, 'attribute', f'Requisito {i}: dato', tuple(ATTRIBUTES))
            item['operator'] = inp.choice(row, 'operator', f'Requisito {i}: comparación', tuple(OPERATORS))
            item['threshold'] = inp.decimal(row, 'threshold', f'Requisito {i}: valor', positive=False, places=4)
        out.append(item)
    return out


def parse_criteria(mode, items):
    out, seen = [], set()
    for i, row in enumerate(items or [], 1):
        ctype = inp.choice(row, 'type', f'Criterio {i}: tipo', ('price_ratio', 'scale', 'manual'))
        scale = []
        if ctype == 'scale':
            for band in inp.items(row, 'scale', f'Criterio {i}: escala', 1, 20):
                lo, hi = band.get('min'), band.get('max')
                scale.append({'min': None if lo in (None, '') else dstr(to_decimal(lo, 'min', allow_negative=True)),
                              'max': None if hi in (None, '') else dstr(to_decimal(hi, 'max', allow_negative=True)),
                              'points': dstr(to_decimal(band.get('points'), 'points'))})
        item = {'position': i, 'code': inp.text(row, 'code', f'Criterio {i}: código', 1, 20, required=False, default=f'C{i}'),
                'name': inp.text(row, 'name', f'Criterio {i}: nombre', 2, 120), 'weight': inp.decimal(row, 'weight', f'Criterio {i}: peso', places=4),
                'type': ctype, 'attribute': inp.choice(row, 'attribute', f'Criterio {i}: dato', tuple(ATTRIBUTES), required=ctype == 'scale'),
                'scale': scale, 'description': inp.text(row, 'description', 'Descripción', 1, 500, required=False)}
        require(item['code'] not in seen, 'validation', f'Criterio {i}: el código {item["code"]} está repetido.', 422)
        seen.add(item['code'])
        out.append(item)
    if mode == 'weighted':
        try:
            validate_criteria('weighted', [{'code': c['code'], 'weight': dstr(c['weight']), 'type': c['type'], 'scale': c['scale']} for c in out])
        except EngineInputError as exc:
            raise ApiError('validation', str(exc), 422, {'criteria': str(exc)})
        require(sum(1 for c in out if c['type'] == 'price_ratio') <= 1, 'validation', 'Solo puede haber un criterio de precio.', 422)
    else:
        require(not out, 'validation', 'Los criterios ponderados solo corresponden al modo “Factores ponderados”.', 422, {'criteria': 'No aplica'})
    return out


def parse_spec(data, case_currency='UYU'):
    spec = data.get('spec') or {}
    require(isinstance(spec, dict), 'validation', 'Pliego inválido.', 422)
    mode = inp.choice(spec, 'mode', 'Criterio de evaluación', MODES, required=False, default='min_price')
    fx = spec.get('fx') or {}
    require(isinstance(fx, dict), 'validation', 'Tipos de cambio inválidos.', 422)
    clean_fx = {}
    for ccy, entry in fx.items():
        require(isinstance(entry, dict) and len(str(ccy)) == 3, 'validation', 'Tipo de cambio inválido.', 422)
        clean_fx[str(ccy).upper()] = {'rate': dstr(to_decimal(entry.get('rate'), 'rate', places=6)),
                                      'date': inp.text(entry, 'date', 'Fecha del tipo de cambio', 8, 10),
                                      'source': inp.text(entry, 'source', 'Fuente del tipo de cambio', 2, 120)}
    flags = spec.get('flags') or {}
    return {
        'mode': mode, 'currency': inp.text(spec, 'currency', 'Moneda de evaluación', 3, 3, required=False, default=case_currency).upper(),
        'minimum_text': inp.text(spec, 'minimum_text', 'Requisitos mínimos (texto)', 12, 4000),
        'delivery_terms': inp.text(spec, 'delivery_terms', 'Condición de entrega', 2, 60, required=False),
        'fx': clean_fx or None, 'flags': {'preferences': inp.boolean(flags, 'preferences'), 'partial_award': inp.boolean(flags, 'partial_award')},
        'similarity_margin': inp.decimal(spec, 'similarity_margin', 'Margen de similitud', required=False, positive=False, default=Decimal('0.05'), maximum=1),
        'requirements': parse_requirements(spec.get('requirements')), 'criteria': parse_criteria(mode, spec.get('criteria')),
        'offer_deadline': inp.moment(spec, 'offer_deadline', 'Plazo de recepción', required=False),
        'reception_channel': inp.choice(spec, 'reception_channel', 'Canal de recepción', ('presencial', 'electronico_arce', 'correo_pliego', 'otro'), required=False),
        'reception_place': inp.text(spec, 'reception_place', 'Lugar de recepción', 2, 200, required=False),
    }


def apply_spec(spec, content):
    for k in ('mode', 'currency', 'minimum_text', 'delivery_terms', 'fx', 'flags', 'similarity_margin', 'offer_deadline',
              'reception_channel', 'reception_place'):
        setattr(spec, k, content[k])
    spec.requirements.clear()
    spec.criteria.clear()
    db.session.flush()
    for r in content['requirements']:
        spec.requirements.append(SpecRequirement(**r))
    for c in content['criteria']:
        spec.criteria.append(SpecCriterion(**c))
    db.session.flush()
    spec.content_hash = spec_hash(spec)


def spec_content(spec):
    return {
        'mode': spec.mode, 'currency': spec.currency, 'minimum_text': spec.minimum_text, 'delivery_terms': spec.delivery_terms, 'fx': spec.fx or {},
        'flags': spec.flags or {}, 'similarity_margin': dstr(Decimal(spec.similarity_margin)),
        'offer_deadline': spec.offer_deadline.isoformat() if spec.offer_deadline else None,
        'reception_channel': spec.reception_channel, 'reception_place': spec.reception_place,
        'requirements': [{'code': r.code, 'text': r.text, 'essential': r.essential, 'kind': r.kind, 'attribute': r.attribute, 'operator': r.operator,
                          'threshold': dstr(r.threshold) if r.threshold is not None else None} for r in spec.requirements],
        'criteria': [{'code': c.code, 'name': c.name, 'weight': dstr(c.weight), 'type': c.type, 'attribute': c.attribute, 'scale': c.scale or []}
                     for c in spec.criteria],
    }


def spec_hash(spec):
    return canonical_hash(spec_content(spec))


def parse_case(data):
    need = inp.text(data, 'need_text', 'Necesidad', 10, 4000)
    case_currency = inp.text(data, 'currency', 'Moneda', 3, 3, required=False, default='UYU').upper()
    return {
        'title': inp.text(data, 'title', 'Nombre de la compra', 5, 200), 'need_text': need,
        'delivery_place': inp.text(data, 'delivery_place', 'Lugar de entrega', 2, 200, required=False),
        'estimated_total': inp.decimal(data, 'estimated_total', 'Estimación con impuestos', places=2),
        'currency': case_currency, 'lines': parse_lines(data), 'spec': parse_spec(data, case_currency),
    }


def create_case(user, data):
    from app.modules.rules.service import suggest_procedure
    area_id = inp.integer(data, 'area_id', 'Área solicitante', minimum=1)
    area = db.session.get(Area, area_id)
    require(area is not None and area.active, 'validation', 'Área solicitante inválida.', 422, {'area_id': 'Elegí un área válida.'})
    assignment = find_assignment(user, 'case.create', area_id)
    require(assignment is not None, 'forbidden', 'No podés crear solicitudes para esa área.', 403)
    c = parse_case(data)
    suggestion = suggest_procedure(c['estimated_total']) if c['currency'] == 'UYU' else None
    case = ProcurementCase(code=next_code(), title=c['title'], area_id=area_id, requester_id=user.id, status='draft', stage=0, version=1,
                           need_text=c['need_text'], delivery_place=c['delivery_place'], currency=c['currency'],
                           estimated_total=c['estimated_total'], procedure_basis={'suggestion': suggestion} if suggestion else {},
                           flags={'round': 1}, updated_at=utcnow())
    db.session.add(case)
    db.session.flush()
    for l in c['lines']:
        db.session.add(RequestLine(case_id=case.id, **l))
    spec = SpecVersion(case_id=case.id, version=1, status='draft', created_by=user.id, mode='min_price', minimum_text='x', similarity_margin=Decimal('0.05'))
    db.session.add(spec)
    db.session.flush()
    apply_spec(spec, c['spec'])
    audit.record(user, 'case.create', 'case', case.id, case=case, reason='Solicitud creada en borrador.', resource_version=1,
                 role_code=assignment.role_code, assignment_id=assignment.id, details={'estimated_total': dstr(case.estimated_total)})
    return case


def supplier_by_id(supplier_id):
    s = db.session.get(Supplier, supplier_id)
    require(s is not None and s.active, 'validation', 'Proveedor inexistente o inactivo.', 422, {'supplier_id': 'Elegí un proveedor válido.'})
    return s
