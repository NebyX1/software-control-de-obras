"""Acciones de la etapa 1 (Solicitud) y clasificación del procedimiento."""
from app.extensions import db
from app.infrastructure.models import RequestLine, SpecVersion, CaseAuthorization
from app.modules.procurement import forms as F, inputs as inp
from app.modules.procurement.framework import action
from app.modules.procurement.service import parse_case, apply_spec
from app.modules.rules.service import suggest_procedure, PROCEDURE_LABELS
from app.shared.contracts import utcnow, dstr
from app.shared.errors import require

CLASSIFIABLE = ('compra_directa', 'concurso_precios', 'licitacion_abreviada', 'licitacion_publica', 'convenio_marco')


@action('request.edit', 'Editar solicitud', 'case.edit_draft', {'draft'}, description='Editá la necesidad, los renglones y los requisitos antes de enviarla.')
def request_edit(ctx, data):
    case = ctx.case
    require(ctx.user.id == case.requester_id or ctx.assignment('case.receive'), 'forbidden', 'Solo quien creó la solicitud o Compras pueden editarla.', 403)
    c = parse_case(data)
    case.title, case.need_text, case.delivery_place = c['title'], c['need_text'], c['delivery_place']
    case.estimated_total, case.currency = c['estimated_total'], c['currency']
    suggestion = suggest_procedure(case.estimated_total) if case.currency == 'UYU' else None
    case.procedure_basis = {'suggestion': suggestion} if suggestion else {}
    for l in db.session.scalars(db.select(RequestLine).where(RequestLine.case_id == case.id)).all():
        db.session.delete(l)
    db.session.flush()
    for l in c['lines']:
        db.session.add(RequestLine(case_id=case.id, **l))
    spec = db.session.scalar(db.select(SpecVersion).where(SpecVersion.case_id == case.id, SpecVersion.version == 1))
    apply_spec(spec, c['spec'])
    return {'reason': 'Solicitud editada en borrador.', 'details': {'estimated_total': dstr(case.estimated_total)}}


def _submit_blockers(ctx):
    out = []
    if not ctx.lines:
        out.append('Cargá al menos un renglón.')
    if ctx.spec is None or not ctx.spec.requirements:
        out.append('Definí al menos un requisito del objeto (editable antes de la aprobación del pliego).')
    return out


@action('request.submit', 'Enviar solicitud', 'case.submit', {'draft'}, blockers=_submit_blockers,
        description='Envía la solicitud a Compras. Una solicitud no es una orden de compra ni compromete gasto.')
def request_submit(ctx, data):
    ctx.case.submitted_at = utcnow()
    return {'status': 'submitted', 'reason': 'Solicitud enviada a Compras.'}


@action('request.receive', 'Recibir y preparar', 'case.receive', {'submitted'},
        description='Compras revisa el alcance, identifica compras agrupadas y comienza la preparación.')
def request_receive(ctx, data):
    return {'status': 'preparation', 'reason': 'Compras recibe la solicitud e inicia la preparación.'}


def _classify_form(ctx):
    sg = (ctx.case.procedure_basis or {}).get('suggestion') or {}
    default = ctx.case.procedure_type or sg.get('suggested')
    return [F.field('procedure_type', 'Procedimiento', 'select', options=F.options([(k, PROCEDURE_LABELS[k]) for k in CLASSIFIABLE]), default=default,
                    help=('Orientación por monto: ' + sg['label'] + '. No determina por sí sola excepciones ni regímenes especiales.') if sg else None),
            F.field('reason', 'Fundamento del encuadre', 'textarea', rows=3, help='Obligatorio si difiere de la orientación por monto.', required=False)]


def _classify_blockers(ctx):
    if db.session.scalar(db.select(CaseAuthorization.id).where(CaseAuthorization.case_id == ctx.case.id, CaseAuthorization.status == 'active')):
        return ['El llamado ya fue autorizado; el encuadre no puede cambiarse sin una nueva actuación.']
    return []


@action('procedure.classify', 'Encuadrar el procedimiento', 'case.classify', {'preparation'}, form=_classify_form, blockers=_classify_blockers,
        done=lambda ctx: ctx.case.procedure_type is not None,
        description='Compras confirma el procedimiento. La orientación por monto es una ayuda, no una resolución.')
def procedure_classify(ctx, data):
    ptype = inp.choice(data, 'procedure_type', 'Procedimiento', CLASSIFIABLE)
    sg = (ctx.case.procedure_basis or {}).get('suggestion') or {}
    reason = inp.text(data, 'reason', 'Fundamento del encuadre', 10, 1000, required=False)
    if sg and sg.get('suggested') != ptype and ptype != 'convenio_marco':
        require(reason, 'validation', 'Fundamento del encuadre: es obligatorio cuando difiere de la orientación por monto.', 422, {'reason': 'Obligatorio.'})
    ctx.case.procedure_type = ptype
    basis = dict(ctx.case.procedure_basis or {})
    basis['decision'] = {'type': ptype, 'reason': reason, 'by': ctx.user.id, 'at': utcnow().isoformat()}
    ctx.case.procedure_basis = basis
    spec = ctx.spec
    if ptype == 'convenio_marco' and spec and spec.status == 'draft':
        spec.mode = 'framework'
        spec.criteria.clear()
    elif ptype != 'convenio_marco' and spec and spec.status == 'draft' and spec.mode == 'framework':
        spec.mode = 'min_price'
    return {'reason': f'Procedimiento: {PROCEDURE_LABELS[ptype]}. {reason or ""}'.strip(), 'details': {'procedure_type': ptype, 'suggested': sg.get('suggested')}}
