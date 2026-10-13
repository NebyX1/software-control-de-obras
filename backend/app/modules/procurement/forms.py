"""Esquemas de formulario que el servidor publica junto a cada acción (el frontend los renderiza de forma genérica)."""


def field(name, label, type='text', required=True, help=None, options=None, default=None, min=None, max=None, rows=None, fields=None, placeholder=None):
    out = {'name': name, 'label': label, 'type': type, 'required': required}
    for k, v in (('help', help), ('options', options), ('default', default), ('min', min), ('max', max), ('rows', rows), ('fields', fields),
                 ('placeholder', placeholder)):
        if v is not None:
            out[k] = v
    return out


def ref_reason(reason_label='Fundamento / constancia', ref_label='Referencia del documento o actuación', ref_help='Número de acto, informe o expediente que respalda esta actuación.'):
    return [field('reference', ref_label, help=ref_help), field('reason', reason_label, 'textarea', rows=3)]


def options(pairs):
    return [{'value': v, 'label': l} for v, l in pairs]
