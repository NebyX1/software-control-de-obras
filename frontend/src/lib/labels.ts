export const STAGE_LABELS = ['Solicitud', 'Preparación', 'Ofertas', 'Evaluación', 'Decisión', 'Orden y entrega', 'Factura y pago', 'Cierre'];

export const PERMISSION_LABELS: Record<string, string> = {
  'case.create': 'Crear solicitudes',
  'case.read': 'Ver compras',
  'spec.manage': 'Preparar pliego',
  'offer.record': 'Registrar ofertas',
  'offer.read': 'Ver ofertas',
  'evaluation.run': 'Evaluar',
  'order.issue': 'Emitir orden',
  'case.close': 'Cerrar compra',
  'supplier.manage': 'Gestionar proveedores',
  'document.upload': 'Cargar documentos',
  'audit.read': 'Ver auditoría',
  'audit.verify': 'Verificar auditoría',
  'admin.users': 'Administrar usuarios',
  'admin.areas': 'Administrar áreas',
  'admin.rules': 'Administrar reglas',
  'ai.use': 'Usar asistencia IA',
  'ai.extract': 'Extraer datos con IA',
  'extraction.review': 'Revisar extracciones',
};

export const ROLE_LABELS: Record<string, string> = {
  administrador: 'Administrador',
  compras: 'Compras',
  tecnica: 'Área técnica',
  auditor: 'Auditor',
};

export const FILTER_OPTIONS = [
  { value: 'all', label: 'Todas las compras' },
  { value: 'active', label: 'En curso' },
  { value: 'attention', label: 'Necesitan atención' },
  { value: 'closed', label: 'Completadas' },
];

export const DOCUMENT_KINDS: Record<string, string> = {
  solicitud: 'Solicitud',
  pliego: 'Pliego',
  oferta: 'Oferta',
  anexo_confidencial: 'Anexo confidencial',
  acta: 'Acta',
  dictamen: 'Dictamen',
  control: 'Control',
  resolucion: 'Resolución',
  comprobante: 'Comprobante',
  factura: 'Factura',
  orden: 'Orden',
  constancia: 'Constancia',
  otro: 'Otro',
};

export const CLASSIFICATION_LABELS: Record<string, string> = {
  public: 'Pública',
  internal: 'Interna',
  confidential: 'Confidencial',
};

export const PROCEDURE_MODE_LABELS: Record<string, string> = {
  min_price: 'Cumple mínimos + menor precio',
  weighted: 'Ponderación explícita',
  framework: 'Convenio marco',
};

export const RECEPTION_LABELS: Record<string, string> = {
  presencial: 'Presencial',
  electronico_arce: 'Electrónico (ARCE)',
  correo_pliego: 'Correo indicado en el pliego',
  otro: 'Otro',
};

export function toneClass(tone: string | null | undefined): string {
  switch (tone) {
    case 'green':
    case 'success':
      return 'badge-green';
    case 'amber':
    case 'warning':
      return 'badge-amber';
    case 'red':
    case 'danger':
      return 'badge-red';
    case 'blue':
    case 'info':
      return 'badge-blue';
    case 'purple':
      return 'badge-purple';
    default:
      return 'badge-neutral';
  }
}

export function friendlyError(code: string | undefined): string {
  switch (code) {
    case 'forbidden':
    case 'competence':
    case 'segregation':
      return 'Tu rol no permite esta acción sobre esta compra.';
    case 'invalid_state':
      return 'La compra cambió de estado. Revisá el expediente antes de continuar.';
    case 'blocked':
      return 'Hay condiciones pendientes que bloquean esta acción.';
    case 'idempotency_conflict':
    case 'busy':
      return 'Otra operación está en curso. Esperá un momento y volvé a intentar.';
    default:
      return '';
  }
}
