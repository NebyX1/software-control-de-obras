"""Semilla demo: usuarios de prueba por rol y los cinco expedientes del modelo HTML, cargados solo con servicios y acciones reales.

La invoca únicamente la CLI `seed-demo` con ALLOW_DEMO_SEED=true. Todo lo creado lleva is_demo=True y códigos DEMO-;
volver a ejecutarla no duplica usuarios, proveedores ni expedientes.
"""
import secrets
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.extensions import db
from app.infrastructure import audit
from app.infrastructure.models import Area, ProcurementCase, RequestLine, Supplier, SupplierStatus, User, UserRole
from app.modules.identity.permissions import ROLE_NAMES
from app.modules.identity.service import validate_password
from app.modules.procurement import framework
from app.modules.procurement.service import create_case
from app.bootstrap import ensure_base_config
from app.shared.contracts import utcnow
from app.shared.errors import ApiError

PASSWORD_ALPHABET = string.ascii_letters + string.digits + '!@#$%^&*-_'
DEMO_LEGAL_BASIS = 'Delegación ficticia para datos de demostración'

AREAS = {'Alumbrado público': 'DEMO-ALUM', 'Servicios generales': 'DEMO-SERV', 'Administración': 'DEMO-ADM', 'Vialidad': 'DEMO-VIAL'}

SUPPLIERS = [
    ('Serrana Iluminación · demo', 'DEMO-PRV-01', 'DEMO-100001'),
    ('Luz del Este · demo', 'DEMO-PRV-02', 'DEMO-100002'),
    ('Faro Económico · demo', 'DEMO-PRV-03', 'DEMO-100003'),
    ('Textil de la Sierra · demo', 'DEMO-PRV-04', 'DEMO-100004'),
    ('Vestir Trabajo · demo', 'DEMO-PRV-05', 'DEMO-100005'),
    ('Papel y Punto · demo', 'DEMO-PRV-06', 'DEMO-100006'),
    ('Áridos Serranos · demo', 'DEMO-PRV-07', 'DEMO-100007'),
    ('Cantera del Este · demo', 'DEMO-PRV-08', 'DEMO-100008'),
]

IP66_MINIMUM = 'IP66, al menos 14.000 lm, garantía mínima de 24 meses y entrega en hasta 30 días corridos.'

# Datos tomados de model\Compra_Clara_Lavalleja.html (seed()). "stage" es el paso del modelo hasta el que el backend permite llegar.
CASES = [
    {'html_id': 'SC-2026-0042', 'title': '120 luminarias LED para barrios', 'area': 'Alumbrado público', 'quantity': 120, 'unit': 'unidades',
     'budget': 220000000, 'procedure': 'licitacion_abreviada', 'mode': 'weighted', 'minimum': IP66_MINIMUM, 'min_warranty': 24, 'max_days': 30,
     'credit_ref': 'PRE-DEMO-2042', 'stage': 3, 'offers': [], 'num': '42',
     'omitted': 'Pliego publicado, convocatoria, sobres, ofertas, verificación técnica, apertura y pasos posteriores: el paso 3 del modelo no los incluye (la apertura además exige plazo vencido, que la semilla no fuerza).'},
    {'html_id': 'SC-2026-0043', 'title': 'Ropa de trabajo para cuadrillas', 'area': 'Servicios generales', 'quantity': 300, 'unit': 'unidades',
     'budget': 345000000, 'procedure': 'licitacion_abreviada', 'mode': 'min_price', 'minimum': 'Tela y talles solicitados; garantía mínima de 24 meses y entrega en hasta 30 días.',
     'credit_ref': 'PRE-DEMO-2043', 'stage': 2, 'offers': [], 'num': '43',
     'omitted': 'Clasificación, disponibilidad, pliego, convocatoria, sobres y ofertas: el paso 2 del modelo solo llega a solicitud recibida.'},
    {'html_id': 'SC-2026-0044', 'title': 'Insumos de oficina', 'area': 'Administración', 'quantity': 100, 'unit': 'unidades',
     'budget': 18400000, 'procedure': 'convenio_marco', 'mode': 'framework', 'minimum': IP66_MINIMUM,
     'credit_ref': 'PRE-DEMO-2044', 'stage': 5, 'num': '44', 'offers': [('Papel y Punto · demo', 140000)],
     'omitted': 'Adjudicación (17.080.000, RES-DEMO-44), control, comunicación, contrato, orden, recepciones y facturas: no hay acción de adjudicación ni de ejecución en el backend para convenio marco.'},
    {'html_id': 'SC-2026-0045', 'title': 'Reparación de motoniveladora', 'area': 'Vialidad', 'quantity': 1, 'unit': 'servicio',
     'budget': 76000000, 'procedure': 'compra_directa', 'mode': 'min_price', 'minimum': 'Diagnóstico, reparación documentada y garantía de 24 meses.',
     'credit_ref': None, 'stage': 1, 'offers': [], 'num': '45',
     'omitted': 'Todo lo posterior al borrador: el modelo lo marca como borrador sin ofertas.'},
    {'html_id': 'SC-2026-0046', 'title': 'Gravilla para caminería rural', 'area': 'Vialidad', 'quantity': 1000, 'unit': 'toneladas',
     'budget': 880000000, 'procedure': 'licitacion_abreviada', 'mode': 'min_price', 'minimum': 'Granulometría conforme; entrega en hasta 30 días y garantía de conformidad contractual.',
     'credit_ref': 'PRE-DEMO-2046', 'stage': 4, 'num': '46', 'offers': [('Áridos Serranos · demo', 630000), ('Cantera del Este · demo', 650000)],
     'omitted': 'Apertura, precios de ofertas, evaluación, dictamen, control observado (OBS-DEMO-46), adjudicación y pasos posteriores: la apertura exige plazo vencido, que la semilla no fuerza.'},
]

GENERAL_OMISSIONS = [
    'Documentos adjuntos del modelo (solicitud, pliego, actas): requieren almacenamiento de archivos.',
    'Apertura de ofertas y registro de precios: exigen plazo vencido; la semilla no altera fechas con SQL.',
    'Evaluación, dictámenes, control, adjudicación, comunicación, contrato, orden, recepciones y facturas: dependen de la apertura.',
]


def _new_password(username):
    while True:
        candidate = ''.join(secrets.choice(PASSWORD_ALPHABET) for _ in range(18))
        try:
            validate_password(candidate, username)
            return candidate
        except ApiError:
            continue


def _ensure_users():
    users, credentials = {}, []
    for role, label in ROLE_NAMES.items():
        username = f'demo-{role}'
        user = db.session.scalar(db.select(User).filter_by(username=username))
        if user is None:
            password = _new_password(username)
            user = User(username=username, email=f'{username}@demo.invalid', full_name=f'Demo {label}', is_demo=True, must_change_password=True)
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            db.session.add(UserRole(user_id=user.id, role_code=role, valid_from=utcnow(), legal_basis=DEMO_LEGAL_BASIS))
            audit.record(None, 'demo.user_created', 'user', user.id, reason=username, role_code=role)
            db.session.commit()
            credentials.append((username, password))
        users[role] = user
    return users, credentials


def _ensure_areas():
    areas = {}
    for html_name, code in AREAS.items():
        area = db.session.scalar(db.select(Area).filter_by(code=code))
        if area is None:
            area = Area(code=code, name=f'{html_name} (demo)', active=True)
            db.session.add(area)
            db.session.commit()
        areas[html_name] = area
    return areas


def _ensure_suppliers(compras):
    suppliers, created = {}, 0
    for name, code, tax_id in SUPPLIERS:
        supplier = db.session.scalar(db.select(Supplier).filter_by(code=code))
        if supplier is None:
            supplier = Supplier(code=code, name=name, tax_id=tax_id, is_demo=True, created_by=compras.id)
            db.session.add(supplier)
            db.session.flush()
            db.session.add(SupplierStatus(supplier_id=supplier.id, kind='rupe', state='activo', valid_from=utcnow().date(),
                                          evidence_ref='RUPE-DEMO-CONSTANCIA', verified_by=compras.id))
            audit.record(None, 'demo.supplier_created', 'supplier', supplier.id, reason=code)
            db.session.commit()
            created += 1
        suppliers[name] = supplier
    return suppliers, created


def _spec(c, deadline=None):
    spec = {'mode': c['mode'], 'currency': 'UYU', 'minimum_text': c['minimum'], 'reception_channel': 'presencial', 'reception_place': 'Mesa de entradas',
            'requirements': [{'code': 'R1', 'text': c['minimum'], 'essential': True, 'kind': 'review'}]}
    if c['mode'] == 'weighted':
        spec['requirements'] += [
            {'code': 'R2', 'text': f"Garantía mínima de {c['min_warranty']} meses", 'essential': True, 'kind': 'numeric',
             'attribute': 'warranty_months', 'operator': 'gte', 'threshold': str(c['min_warranty'])},
            {'code': 'R3', 'text': f"Entrega hasta {c['max_days']} días", 'essential': True, 'kind': 'numeric',
             'attribute': 'delivery_days', 'operator': 'lte', 'threshold': str(c['max_days'])}]
        spec['criteria'] = [
            {'code': 'price', 'name': 'Precio', 'weight': '70', 'type': 'price_ratio'},
            {'code': 'delivery', 'name': 'Entrega', 'weight': '20', 'type': 'scale', 'attribute': 'delivery_days',
             'scale': [{'min': '0', 'max': '10', 'points': '20'}, {'min': '11', 'max': '20', 'points': '10'}, {'min': '21', 'max': '30', 'points': '0'}]},
            {'code': 'warranty', 'name': 'Garantía', 'weight': '10', 'type': 'scale', 'attribute': 'warranty_months',
             'scale': [{'min': '60', 'max': None, 'points': '10'}, {'min': '36', 'max': '59', 'points': '6'}, {'min': '24', 'max': '35', 'points': '3'}]}]
    if deadline:
        spec['offer_deadline'] = deadline
    return spec


def _steps(c, suppliers, line_id, now):
    convenio = c['procedure'] == 'convenio_marco'
    deadline = (now + timedelta(days=20)).isoformat()
    published = (now - timedelta(days=30)).date().isoformat()
    steps = []
    if c['stage'] >= 2:
        steps += [('solicitante', 'request.submit', {}), ('compras', 'request.receive', {})]
    if c['stage'] >= 3:
        steps += [
            ('compras', 'procedure.classify', {'procedure_type': c['procedure'], 'reason': 'Encuadre según monto y tipo de compra (datos de demostración).'}),
            ('contaduria', 'availability.register', {
                'fiscal_year': 2026, 'item': c['title'], 'funding_source': 'Rentas generales', 'total_amount': str(c['budget']),
                'credit_support_ref': c['credit_ref'], 'amount': str(c['budget']), 'availability_date': '2026-10-01', 'support_ref': f"DISP-DEMO-{c['num']}"})]
    if c['stage'] >= 4:
        if not convenio:
            steps.append(('compras', 'spec.save', {'spec': _spec(c, deadline)}))
        steps += [
            ('compras', 'spec.approve', {}),
            ('ordenador', 'call.authorize', {'reference': f"RES-DEMO-{c['num']}", 'reason': 'Llamado autorizado con datos ficticios de demostración.'})]
        if not convenio:
            steps.append(('compras', 'publicity.register', {'kind': 'convocatoria', 'state': 'external_constancia',
                                                            'reference': f"ARCE-DEMO-{c['num']}", 'published_on': published}))
            for name, _net in c['offers']:
                steps.append(('recepcion', 'envelope.register', {'supplier_id': suppliers[name].id, 'channel': 'presencial',
                                                                 'custody_note': 'Sobre recibido en mesa de entradas (datos demo).'}))
    if c['stage'] >= 5 and convenio:
        name, net = c['offers'][0]
        unit_price = (Decimal(net) / Decimal(c['quantity'])).quantize(Decimal('0.01'))
        steps.append(('compras', 'framework.select', {
            'supplier_id': suppliers[name].id, 'agreement_ref': 'CM-DEMO-01', 'evidence_note': 'Constancia ficticia de selección en convenio marco.',
            'lines': [{'request_line_id': line_id, 'unit_price': str(unit_price), 'tax_rate': '22'}]}))
    return steps


def _ensure_cases(users, areas, suppliers):
    reports = []
    now = datetime.now(timezone.utc)
    for c in CASES:
        need_text = f"Expediente de demostración {c['html_id']} (datos ficticios): {c['title']}."
        existing = db.session.scalar(db.select(ProcurementCase).filter_by(is_demo=True, need_text=need_text))
        if existing is not None:
            reports.append({'html_id': c['html_id'], 'code': existing.code, 'title': c['title'], 'status': 'ya existía', 'omitted': c['omitted']})
            continue
        try:
            case = create_case(users['solicitante'], {
                'title': c['title'], 'area_id': areas[c['area']].id, 'need_text': need_text, 'delivery_place': 'Depósito departamental, Minas',
                'estimated_total': str(c['budget']), 'currency': 'UYU',
                'lines': [{'description': c['title'], 'quantity': str(c['quantity']), 'unit': c['unit']}], 'spec': _spec(c)})
            case.is_demo = True
            db.session.commit()
        except ApiError as exc:
            db.session.rollback()
            reports.append({'html_id': c['html_id'], 'code': None, 'title': c['title'], 'status': f'no creado ({exc.code})', 'omitted': c['omitted']})
            continue
        code = case.code
        line_id = db.session.scalar(db.select(RequestLine.id).filter_by(case_id=case.id))
        done, failure = 0, None
        for role, action, payload in _steps(c, suppliers, line_id, now):
            try:
                framework.execute(code, action, payload, users[role])
                done += 1
            except ApiError as exc:
                db.session.rollback()
                failure = f'{action}: {exc.code}'
                break
        reports.append({'html_id': c['html_id'], 'code': code, 'title': c['title'], 'status': f'pasos ejecutados: {done}', 'failure': failure, 'omitted': c['omitted']})
    return reports


def seed():
    ensure_base_config()
    users, credentials = _ensure_users()
    areas = _ensure_areas()
    suppliers, suppliers_created = _ensure_suppliers(users['compras'])
    cases = _ensure_cases(users, areas, suppliers)
    return {'credentials': credentials, 'suppliers_created': suppliers_created, 'cases': cases, 'general_omissions': GENERAL_OMISSIONS}
