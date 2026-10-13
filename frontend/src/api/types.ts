export interface User {
  id: number;
  username: string;
  email: string;
  full_name: string;
  area_id: number | null;
  area: string | null;
  permissions: string[];
  roles: string[];
  must_change_password: boolean;
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
}

export interface FormOption {
  value: string;
  label: string;
}

export interface FormField {
  name: string;
  label: string;
  type: string;
  required: boolean;
  help?: string;
  options?: FormOption[];
  default?: unknown;
  min?: number;
  max?: number;
  rows?: number;
  fields?: FormField[];
  placeholder?: string;
}

export interface ActionInfo {
  name: string;
  label: string;
  description: string;
  responsible: string[] | string;
  can: boolean;
  blockers: string[];
  form: FormField[];
  danger: boolean;
  done: boolean;
}

export interface NextStep {
  action: string;
  label: string;
  responsible: string[] | string;
  can: boolean;
  blockers: string[];
}

export interface CaseSummary {
  code: string;
  title: string;
  area: string;
  area_id: number;
  status: string;
  status_label: string;
  tone: string;
  stage: number;
  stage_label: string;
  estimated_total: string | null;
  currency: string;
  procedure_type: string;
  procedure_label: string;
  suggested_procedure: string;
  is_demo: boolean;
  updated_at: string;
  created_at: string;
  version: number;
}

export interface CaseLine {
  id: number;
  position: number;
  description: string;
  quantity: string;
  unit: string;
  estimated_unit_price: string | null;
  tax_rate: string | null;
}

export interface RequirementSpec {
  id?: number;
  code: string;
  text: string;
  essential: boolean;
  kind: 'review' | 'numeric';
  attribute: string | null;
  operator: string | null;
  threshold: string | null;
  unit: string | null;
}

export interface CriterionSpec {
  id?: number;
  code: string;
  name: string;
  weight: string;
  type: 'price_ratio' | 'scale' | 'manual';
  attribute: string | null;
  scale: { min: string; max?: string | null; points: string }[];
  description?: string | null;
}

export interface SpecJson {
  id: number;
  version: number;
  status: string;
  mode: 'min_price' | 'weighted' | 'framework';
  currency: string;
  fx: Record<string, unknown>;
  minimum_text: string | null;
  delivery_terms: string | null;
  flags: Record<string, unknown>;
  similarity_margin: string | null;
  offer_deadline: string | null;
  reception_channel: string | null;
  reception_place: string | null;
  requirements: RequirementSpec[];
  criteria: CriterionSpec[];
}

export interface DocumentVersion {
  version: number;
  sha256: string;
  size: number;
  mime: string;
  original_name: string;
  text_status: string;
  page_count: number | null;
  uploaded_at: string;
}

export interface CaseDocument {
  id: number;
  kind: string;
  title: string;
  classification: string;
  sealed: boolean;
  envelope_id: number | null;
  can_download: boolean;
  external_reference: string | null;
  created_at: string;
  versions: DocumentVersion[];
}

export interface OfferLine {
  request_line_id: number;
  unit_price: string | null;
  tax_rate: string | null;
  discount: string | null;
  quantity: string | null;
}

export interface OfferData {
  prices_include_tax: boolean;
  freight: string | null;
  freight_includes_tax: boolean;
  freight_tax_rate: string | null;
  discount_total: string | null;
  delivery_days: number | null;
  warranty_months: number | null;
  delivery_terms: string | null;
  reason: string | null;
  recorded_by: string | null;
  recorded_at: string | null;
  lines: OfferLine[];
}

export interface OfferReview {
  requirement_id: number;
  result: string;
  treatment: string | null;
  observed_value: string | null;
  document_id: number | null;
  page: number | null;
  quote: string | null;
  note: string | null;
  reviewer: string | null;
  reviewed_at: string | null;
}

export interface ManualScore {
  criterion_id: number;
  points: string;
  evidence: string | null;
  evaluator: string | null;
}

export interface Offer {
  id: number;
  supplier_id: number;
  supplier: string;
  currency: string;
  status: string;
  data_version: number | null;
  data: OfferData | null;
  reviews: OfferReview[];
  manual_scores: ManualScore[];
}

export interface EvaluationOfferResult {
  id: number;
  name: string;
  status: 'admissible' | 'excluded' | 'pending';
  reasons: string[];
  pending: string[];
  warnings: string[];
  requirements: Record<string, unknown>[];
  totals: { commercial: string | null; comparable: string | null; currency: string } | null;
  criteria: Record<string, unknown>[];
  score: string | null;
  score_display: string | null;
  rank: number | null;
}

export interface EvaluationResult {
  offers: EvaluationOfferResult[];
  [key: string]: unknown;
}

export interface Evaluation {
  id: number;
  version: number;
  status: string;
  stale_reason: string | null;
  mode: string;
  engine_version: string;
  input_hash: string;
  spec_version_id: number;
  created_at: string;
  result: EvaluationResult | null;
  recommended_offer_id: number | null;
}

export interface EvaluationHistoryItem {
  id: number;
  version: number;
  status: string;
  created_at: string;
  recommended_offer_id: number | null;
  stale_reason?: string | null;
}

export interface EventJson {
  id: number;
  at: string;
  actor: string | null;
  role: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  version: number | null;
  reason: string | null;
  reference: string | null;
  hash: string;
}

export interface CaseDetail extends CaseSummary {
  need_text: string;
  delivery_place: string | null;
  requester: string | null;
  procedure_basis: string | null;
  branch: string | null;
  flags: Record<string, unknown>;
  round: number;
  submitted_at: string | null;
  closed_at: string | null;
  stages: string[];
  lines: CaseLine[];
  spec: SpecJson | null;
  spec_versions: Record<string, unknown>[];
  offers: Offer[];
  offers_sealed: boolean;
  evaluation: Evaluation | null;
  evaluations: EvaluationHistoryItem[];
  documents: CaseDocument[];
  recent_events: EventJson[];
  actions: ActionInfo[];
  next: NextStep | null;
  can_edit_draft: boolean;
  preparation: Record<string, unknown>;
  reception: Record<string, unknown> | null;
  envelopes: Record<string, unknown>[];
  openings: Record<string, unknown>[];
  order: Record<string, unknown> | null;
  invoices: Record<string, unknown>[];
  payments: Record<string, unknown>[];
  modifications: Record<string, unknown>[];
  closure: Record<string, unknown> | null;
  branches: Record<string, unknown>[];
  [key: string]: unknown;
}

export interface ActionResponse extends CaseDetail {
  replayed?: boolean;
}

export interface Explanation {
  title: string;
  source: string;
  sections: { heading: string; items: string[] }[];
}

export interface ScenarioResult {
  result: EvaluationResult;
  isolated: boolean;
  note: string;
}

export interface DashboardStats {
  active: number;
  total: number;
  ready_to_compare: number;
  attention: number;
  events: number;
}

export interface DashboardData {
  stats: DashboardStats;
  recent: EventJson[];
  cases: CaseSummary[];
  stages: string[];
}

export interface Area {
  id: number;
  code: string;
  name: string;
}

export interface Supplier {
  id: number;
  code: string;
  name: string;
  tax_id: string | null;
  country: string;
  contact_email: string | null;
  active: boolean;
  is_demo: boolean;
}

export interface SupplierStatusInput {
  kind: 'rupe' | 'impedimento' | 'antecedente';
  state: string;
  valid_from?: string;
  valid_to?: string;
  evidence_ref: string;
  note?: string;
}

export interface AuditItem {
  id: number;
  at: string;
  actor: string | null;
  role: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  version: number | null;
  reason: string | null;
  reference: string | null;
  hash: string;
}

export interface AuditVerification {
  ok: boolean;
  verified: number;
  failure: string | null;
  notice: string;
}

export interface RuleVersion {
  code: string;
  status: string;
  valid_from: string;
}

export interface RulesResponse {
  active: Record<string, unknown> | null;
  versions: RuleVersion[];
  notice: string;
}

export interface NormativeSource {
  code: string;
  organismo: string;
  titulo: string;
  url: string;
  consulta: string;
  hallazgo: string;
  tipo: string;
  scope: string;
  kind: string;
  validation_status: string;
}

export interface AdminRole {
  code: string;
  name: string;
}

export interface AdminAssignment {
  id: number;
  role: string;
  role_name: string | null;
  area_id: number | null;
  valid_from: string | null;
  valid_to: string | null;
  max_amount: string | null;
  procedures: string[] | null;
  legal_basis: string | null;
  revoked: boolean;
  delegated_from_id: number | null;
}

export interface AdminUser {
  id: number;
  username: string;
  email: string;
  full_name: string;
  active: boolean;
  area_id: number | null;
  is_demo: boolean;
  locked: boolean;
  last_login_at: string | null;
  assignments: AdminAssignment[];
}

export interface SegregationRule {
  id: number;
  action_a: string;
  action_b: string;
  active: boolean;
  reason: string | null;
}

export interface ChatSource {
  code?: string;
  title?: string;
  url?: string;
  [key: string]: unknown;
}

export interface ChatFinal {
  text: string;
  cited: unknown[];
  warnings: string[];
  conversation_id: string | null;
}

export interface AiTask {
  id: number;
  kind: string;
  status: string;
  attempts: number;
  error: string | null;
  result: Record<string, unknown> | null;
  created_at: string;
}

export interface ExtractedField {
  id: number;
  name: string;
  value: string | null;
  status: string;
  evidence: Record<string, unknown> | null;
  [key: string]: unknown;
}

export interface AiDraft {
  id: number;
  kind: string;
  content: string;
  warnings: string[];
  sources: unknown;
  model: string | null;
  evaluation_id: number | null;
  created_at: string;
  label: string;
}

export interface Inconsistency {
  severity: string;
  code: string;
  message: string;
  offer_id: number | null;
}
