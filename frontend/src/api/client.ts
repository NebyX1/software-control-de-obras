import axios, { AxiosError } from 'axios';

export class ApiError extends Error {
  status: number;
  code: string;
  fields: Record<string, string>;
  requestId?: string;
  extra: Record<string, unknown>;

  constructor(status: number, code: string, message: string, fields: Record<string, string> = {}, requestId?: string, extra: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields;
    this.requestId = requestId;
    this.extra = extra;
  }
}

// El token CSRF vive solo en memoria: se renueva en cada respuesta de sesión.
let csrfToken: string | null = null;

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}

export const api = axios.create({
  baseURL: '/api/v1',
  withCredentials: true,
  timeout: 65000,
  headers: { Accept: 'application/json' },
});

api.interceptors.request.use((config) => {
  const method = (config.method || 'get').toUpperCase();
  if (csrfToken && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    config.headers.set('X-CSRF-Token', csrfToken);
  }
  return config;
});

function safeMessage(status: number, message?: string) {
  if (status >= 500) return 'El servidor no pudo completar la operación. Intentá de nuevo en unos instantes.';
  if (status === 404) return message || 'No encontramos lo que buscabas.';
  if (status === 401) return message || 'Tu sesión venció. Iniciá sesión de nuevo.';
  return message || 'No se pudo completar la operación.';
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (error instanceof AxiosError) {
    const status = error.response?.status ?? 0;
    const data = error.response?.data as
      | { code?: string; message?: string; fields?: Record<string, string>; request_id?: string; extra?: Record<string, unknown> }
      | undefined;
    if (status === 0) {
      return new ApiError(0, 'network', 'No hay conexión con el servidor. Revisá la red e intentá de nuevo.');
    }
    return new ApiError(
      status,
      data?.code ?? (status >= 500 ? 'server_error' : 'error'),
      safeMessage(status, data?.message),
      data?.fields ?? {},
      data?.request_id,
      data?.extra ?? {},
    );
  }
  return new ApiError(0, 'unknown', 'Ocurrió un error inesperado. Intentá de nuevo.');
}

export function isConflict(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 409 && error.code === 'version_conflict';
}

/**
 * Ejecuta una llamada al backend y normaliza el error. Ante un 403 de CSRF
 * renueva el token desde /auth/me y pide al usuario que reintente.
 */
export async function request<T>(promise: Promise<{ data: T }>): Promise<T> {
  try {
    const res = await promise;
    return res.data;
  } catch (error) {
    const apiError = toApiError(error);
    if (apiError.status === 403 && /sesión de seguridad/i.test(apiError.message)) {
      try {
        const me = await api.get<{ csrf_token: string }>('/auth/me');
        setCsrfToken(me.data.csrf_token ?? null);
      } catch {
        setCsrfToken(null);
      }
      throw new ApiError(403, 'csrf', 'La sesión de seguridad cambió. Revisá los datos y volvé a intentar.');
    }
    throw apiError;
  }
}
