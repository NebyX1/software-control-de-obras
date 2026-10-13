"""Proveedores (con estados RUPE/impedimentos respaldados), áreas y créditos registrados."""
import re
from flask import Blueprint, jsonify, request
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.infrastructure import audit
from app.infrastructure.models import Area, Supplier, SupplierStatus, BudgetLine
from app.modules.identity.permissions import find_assignment
from app.modules.identity.service import auth_required, perm_required
from app.modules.procurement import inputs as inp
from app.shared.contracts import dstr, iso_utc
from app.shared.errors import ApiError, require

bp = Blueprint('organization', __name__, url_prefix='/api/v1')
TAX_ID = re.compile(r'^[A-Za-z0-9.\-]{5,30}$')


def supplier_json(s, with_status=True):
    out = {'id': s.id, 'code': s.code, 'name': s.name, 'tax_id': s.tax_id, 'country': s.country, 'contact_email': s.contact_email, 'active': s.active, 'is_demo': s.is_demo}
    if with_status:
        rows = db.session.scalars(db.select(SupplierStatus).where(SupplierStatus.supplier_id == s.id).order_by(SupplierStatus.id.desc())).all()
        out['statuses'] = [{'id': r.id, 'kind': r.kind, 'state': r.state, 'valid_from': r.valid_from.isoformat() if r.valid_from else None,
                            'valid_to': r.valid_to.isoformat() if r.valid_to else None, 'evidence_ref': r.evidence_ref, 'note': r.note, 'at': iso_utc(r.created_at)} for r in rows]
    return out


@bp.get('/areas')
@auth_required
def areas():
    return jsonify(items=[{'id': a.id, 'code': a.code, 'name': a.name} for a in db.session.scalars(db.select(Area).where(Area.active.is_(True)).order_by(Area.name))])


@bp.get('/suppliers')
@perm_required('supplier.read')
def suppliers():
    q = (request.args.get('q') or '').strip()
    query = db.select(Supplier).order_by(Supplier.name)
    if q:
        like = f'%{q[:80]}%'
        query = query.where((Supplier.name.like(like)) | (Supplier.tax_id.like(like)))
    return jsonify(items=[supplier_json(s) for s in db.session.scalars(query.limit(200))])


@bp.post('/suppliers')
@perm_required('supplier.manage')
def create_supplier():
    data = request.get_json(silent=True) or {}
    name = inp.text(data, 'name', 'Nombre', 3, 200)
    tax = inp.text(data, 'tax_id', 'RUT / identificador fiscal', 5, 30, required=False)
    require(tax is None or TAX_ID.match(tax), 'validation', 'Identificador fiscal inválido.', 422, {'tax_id': 'Formato inválido.'})
    n = (db.session.scalar(db.select(db.func.count(Supplier.id))) or 0) + 1
    s = Supplier(code=f'PR-{n:05d}', name=name, tax_id=tax, country=inp.text(data, 'country', 'País', 2, 2, required=False, default='UY').upper(),
                 contact_email=inp.text(data, 'contact_email', 'Correo', 5, 120, required=False), created_by=current_user.id)
    db.session.add(s)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise ApiError('duplicate_supplier', 'Ya existe un proveedor con ese identificador fiscal o código.', 409)
    a = find_assignment(current_user, 'supplier.manage')
    audit.record(current_user, 'supplier.create', 'supplier', s.id, reason=name, reference=tax, role_code=a.role_code if a else None, assignment_id=a.id if a else None)
    db.session.commit()
    return jsonify(supplier_json(s)), 201


@bp.post('/suppliers/<int:supplier_id>/status')
@perm_required('supplier.manage')
def supplier_status(supplier_id):
    s = db.session.get(Supplier, supplier_id)
    require(s is not None, 'not_found', 'Proveedor no encontrado.', 404)
    data = request.get_json(silent=True) or {}
    row = SupplierStatus(supplier_id=s.id, kind=inp.choice(data, 'kind', 'Tipo', ('rupe', 'impedimento', 'antecedente')),
                         state=inp.text(data, 'state', 'Estado', 2, 40), valid_from=inp.day(data, 'valid_from', 'Vigente desde', required=False),
                         valid_to=inp.day(data, 'valid_to', 'Vigente hasta', required=False), evidence_ref=inp.text(data, 'evidence_ref', 'Respaldo', 3, 200),
                         note=inp.text(data, 'note', 'Nota', 1, 500, required=False), verified_by=current_user.id)
    db.session.add(row)
    db.session.flush()
    a = find_assignment(current_user, 'supplier.manage')
    audit.record(current_user, 'supplier.status', 'supplier', s.id, reason=f'{row.kind}: {row.state}', reference=row.evidence_ref, role_code=a.role_code if a else None,
                 assignment_id=a.id if a else None, details={'valid_from': str(row.valid_from), 'valid_to': str(row.valid_to)})
    db.session.commit()
    return jsonify(supplier_json(s)), 201


def budget_json(b):
    return {'id': b.id, 'fiscal_year': b.fiscal_year, 'item': b.item, 'funding_source': b.funding_source, 'total_amount': dstr(b.total_amount),
            'committed_amount': dstr(b.committed_amount), 'free_amount': dstr(b.total_amount - b.committed_amount), 'support_ref': b.support_ref}


@bp.get('/budget-lines')
@auth_required
def budget_lines():
    require(find_assignment(current_user, 'availability.register') or find_assignment(current_user, 'budget.manage'), 'forbidden', 'Sin permiso.', 403)
    return jsonify(items=[budget_json(b) for b in db.session.scalars(db.select(BudgetLine).order_by(BudgetLine.fiscal_year.desc(), BudgetLine.item))])
