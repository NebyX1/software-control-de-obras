import { api, request } from './client';
import type {
  ActionResponse,
  AdminRole,
  AdminUser,
  AiDraft,
  AiTask,
  Area,
  AuditItem,
  AuditVerification,
  CaseDetail,
  CaseDocument,
  CaseSummary,
  DashboardData,
  EventJson,
  ExtractedField,
  Explanation,
  Inconsistency,
  NormativeSource,
  Paged,
  RulesResponse,
  ScenarioResult,
  SegregationRule,
  Supplier,
  User,
} from './types';

export interface ChallengeResponse {
  csrf_token: string;
  captcha: { question: string } | null;
  two_factor: boolean;
}

export interface LoginResponse {
  requires_2fa?: boolean;
  preview?: string;
  user?: User;
  csrf_token?: string;
}

export const authApi = {
  challenge: () => request(api.get<ChallengeResponse>('/auth/challenge')),
  me: () => request(api.get<{ user: User; csrf_token: string }>('/auth/me')),
  login: (email: string, password: string, captcha?: string) =>
    request(api.post<LoginResponse>('/auth/login', { email, password, captcha })),
  verify2fa: (code: string) => request(api.post<{ user: User; csrf_token: string }>('/auth/verify-2fa', { code })),
  logout: () => request(api.post<{ ok: boolean; csrf_token: string }>('/auth/logout')),
  changePassword: (current: string, next: string) =>
    request(api.post<{ ok: boolean }>('/auth/change-password', { current, new: next })),
};

export interface CaseListParams {
  q?: string;
  filter?: string;
  stage?: number;
  sort?: string;
  page?: number;
  per_page?: number;
}

export const casesApi = {
  list: (params: CaseListParams) => request(api.get<Paged<CaseSummary>>('/cases', { params })),
  get: (code: string) => request(api.get<CaseDetail>(`/cases/${encodeURIComponent(code)}`)),
  create: (body: Record<string, unknown>, idempotencyKey: string) =>
    request(api.post<CaseDetail>('/cases', body, { headers: { 'Idempotency-Key': idempotencyKey } })),
  action: (code: string, name: string, body: Record<string, unknown>) =>
    request(api.post<ActionResponse>(`/cases/${encodeURIComponent(code)}/actions/${name}`, body)),
  events: (code: string, before?: number) =>
    request(api.get<{ items: EventJson[] }>(`/cases/${encodeURIComponent(code)}/events`, { params: { before, limit: 50 } })),
  explanation: (code: string) => request(api.get<Explanation>(`/cases/${encodeURIComponent(code)}/explanation`)),
  scenario: (code: string, overrides: Record<string, unknown>[]) =>
    request(api.post<ScenarioResult>(`/cases/${encodeURIComponent(code)}/evaluation/scenario`, { overrides })),
  dashboard: () => request(api.get<DashboardData>('/dashboard')),
};

export const documentsApi = {
  upload: (code: string, form: FormData) =>
    request(api.post<CaseDocument>(`/cases/${encodeURIComponent(code)}/documents`, form, { headers: { 'Content-Type': 'multipart/form-data' } })),
  uploadVersion: (documentId: number, form: FormData) =>
    request(api.post<CaseDocument>(`/documents/${documentId}/versions`, form, { headers: { 'Content-Type': 'multipart/form-data' } })),
  download: async (documentId: number, version: number, fileName: string) => {
    const res = await api.get<Blob>(`/documents/${documentId}/versions/${version}/download`, { responseType: 'blob' });
    triggerDownload(res.data, fileName);
  },
};

export const organizationApi = {
  areas: () => request(api.get<{ items: Area[] }>('/areas')),
  suppliers: (q?: string) => request(api.get<{ items: Supplier[] }>('/suppliers', { params: { q: q || undefined } })),
  createSupplier: (body: Record<string, unknown>) => request(api.post<Supplier>('/suppliers', body)),
  supplierStatus: (id: number, body: Record<string, unknown>) =>
    request(api.post<Supplier>(`/suppliers/${id}/status`, body)),
};

export const rulesApi = {
  rules: () => request(api.get<RulesResponse>('/rules')),
  suggest: (amount: string) => request(api.get<Record<string, unknown>>('/rules/suggest', { params: { amount } })),
  normative: (q?: string) => request(api.get<{ items: NormativeSource[]; notice: string }>('/normative/sources', { params: { q: q || undefined } })),
};

export const auditApi = {
  list: (params: { q?: string; case?: string; page?: number; per_page?: number }) =>
    request(api.get<Paged<AuditItem>>('/audit', { params })),
  verify: () => request(api.get<AuditVerification>('/audit/verify')),
  exportCsv: async () => {
    const res = await api.get<Blob>('/audit/export', { responseType: 'blob' });
    triggerDownload(res.data, 'auditoria-compra-clara.csv');
  },
};

export const adminApi = {
  users: () => request(api.get<{ items: AdminUser[]; roles: AdminRole[] }>('/admin/users')),
  createUser: (body: Record<string, unknown>) =>
    request(api.post<{ user: AdminUser; temporary_password: string; notice: string }>('/admin/users', body)),
  patchUser: (id: number, body: Record<string, unknown>) =>
    request(api.patch<{ user: AdminUser; temporary_password?: string }>(`/admin/users/${id}`, body)),
  addAssignment: (userId: number, body: Record<string, unknown>) =>
    request(api.post<{ user: AdminUser }>(`/admin/users/${userId}/assignments`, body)),
  revokeAssignment: (id: number, reason?: string) =>
    request(api.post<{ user: AdminUser }>(`/admin/assignments/${id}/revoke`, { reason })),
  createArea: (body: Record<string, unknown>) => request(api.post<Area>('/admin/areas', body)),
  segregation: () => request(api.get<{ items: SegregationRule[] }>('/admin/segregation')),
  patchSegregation: (id: number, body: Record<string, unknown>) =>
    request(api.patch<{ ok: boolean }>(`/admin/segregation/${id}`, body)),
  createRuleSet: (body: Record<string, unknown>) => request(api.post<{ code: string; status: string }>('/admin/rule-sets', body)),
  activateRuleSet: (code: string, validationNote: string) =>
    request(api.post<Record<string, unknown>>(`/admin/rule-sets/${encodeURIComponent(code)}/activate`, { validation_note: validationNote })),
  createHoliday: (day: string, name: string) => request(api.post<Record<string, unknown>>('/admin/holidays', { day, name })),
};

export const aiApi = {
  extract: (code: string, offerId: number, documentId: number) =>
    request(api.post<AiTask>(`/ai/cases/${encodeURIComponent(code)}/extract`, { offer_id: offerId, document_id: documentId })),
  task: (id: number) => request(api.get<AiTask>(`/ai/tasks/${id}`)),
  fields: (code: string) => request(api.get<{ items: ExtractedField[]; notice: string }>(`/ai/cases/${encodeURIComponent(code)}/fields`)),
  reviewField: (id: number, body: { action: 'confirm' | 'correct' | 'reject'; value?: string; note?: string }) =>
    request(api.post<ExtractedField>(`/ai/fields/${id}/review`, body)),
  explain: (code: string) => request(api.post<AiDraft>(`/ai/cases/${encodeURIComponent(code)}/explain`)),
  draft: (code: string, kind: 'borrador_dictamen' | 'borrador_analisis', force = false) =>
    request(api.post<AiDraft>(`/ai/cases/${encodeURIComponent(code)}/draft${force ? '?force=1' : ''}`, { kind })),
  inconsistencies: (code: string) =>
    request(api.get<{ items: Inconsistency[]; notice: string }>(`/ai/cases/${encodeURIComponent(code)}/inconsistencies`)),
};

export function triggerDownload(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
