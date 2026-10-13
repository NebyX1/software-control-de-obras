"""Acceso por recurso: un usuario solo ve expedientes de las áreas incluidas en sus asignaciones vigentes."""
from sqlalchemy import false
from app.extensions import db
from app.infrastructure.models import ProcurementCase
from app.modules.identity.permissions import active_assignments, ROLE_PERMS


def readable_areas(user, assignments=None):
    """None = todas las áreas; lista = solo esas; [] = ninguna."""
    areas, any_all = set(), False
    for a in (assignments if assignments is not None else active_assignments(user)):
        if 'case.read' in ROLE_PERMS.get(a.role_code, ()):
            if a.area_id is None:
                any_all = True
            else:
                areas.add(a.area_id)
    return None if any_all else sorted(areas)


def can_read_case(user, case, assignments=None):
    areas = readable_areas(user, assignments)
    return areas is None or case.area_id in areas


def visible_cases_query(user):
    areas = readable_areas(user)
    q = db.select(ProcurementCase)
    if areas is None:
        return q
    if not areas:
        return q.where(false())
    return q.where(ProcurementCase.area_id.in_(areas))


def get_case(user, code, lock=False):
    from app.shared.errors import ApiError
    q = db.select(ProcurementCase).where(ProcurementCase.code == code)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    case = db.session.scalar(q)
    if case is None or not can_read_case(user, case):
        raise ApiError('not_found', 'No se encontró el expediente.', 404)
    return case
