import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { toApiError } from '../api/client';
import { friendlyError, toneClass } from '../lib/labels';

export function Badge({ tone, children }: { tone?: string | null; children: ReactNode }) {
  return <span className={`badge ${toneClass(tone)}`}>{children}</span>;
}

export function Notice({ tone = '', children, role = 'status' }: { tone?: 'amber' | 'green' | 'red' | 'blue' | ''; children: ReactNode; role?: 'status' | 'alert' }) {
  return <div className={`notice ${tone}`} role={role}>{children}</div>;
}

export function ErrorNotice({ error }: { error: unknown }) {
  const e = toApiError(error);
  const hint = friendlyError(e.code);
  return (
    <Notice tone="red" role="alert">
      <div>
        <strong>{e.message}</strong>
        {hint && <div>{hint}</div>}
      </div>
    </Notice>
  );
}

export function Loading({ label = 'Cargando…' }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children}
    </div>
  );
}

export function Stat({ label, value, glyph, tone = '' }: { label: string; value: ReactNode; glyph: string; tone?: string }) {
  return (
    <div className="card stat">
      <div className="stat-top">
        <span className={`icon-box ${tone}`} aria-hidden="true">{glyph}</span>
      </div>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

interface ModalProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}

export function Modal({ title, onClose, children, footer, wide = false }: ModalProps) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);

  useEffect(() => {
    closeRef.current = onClose;
  });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeRef.current();
    };
    document.addEventListener('keydown', onKey);
    dialogRef.current?.focus();
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className={`modal ${wide ? 'wide' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        ref={dialogRef}
      >
        <div className="modal-head">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="btn secondary small" onClick={onClose}>Cerrar</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  );
}

export function Pager({ page, perPage, total, onPage }: { page: number; perPage: number; total: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / perPage));
  return (
    <div className="table-footer">
      <span>{total} {total === 1 ? 'resultado' : 'resultados'} · página {page} de {pages}</span>
      <div className="pager">
        <button type="button" className="btn secondary small" disabled={page <= 1} onClick={() => onPage(page - 1)}>Anterior</button>
        <button type="button" className="btn secondary small" disabled={page >= pages} onClick={() => onPage(page + 1)}>Siguiente</button>
      </div>
    </div>
  );
}

type Tone = 'ok' | 'error';
type Notifier = (message: string, tone?: Tone) => void;

const ToastContext = createContext<Notifier | null>(null);

interface ToastItem {
  id: number;
  message: string;
  tone: Tone;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const notify = useCallback<Notifier>((message, tone = 'ok') => {
    const id = Date.now() + Math.random();
    setItems((prev) => [...prev, { id, message, tone }]);
    window.setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), 5000);
  }, []);

  const dismiss = (id: number) => setItems((prev) => prev.filter((t) => t.id !== id));

  return (
    <ToastContext.Provider value={notify}>
      {children}
      <div className="toast-area" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.tone === 'error' ? 'error' : ''}`} role={t.tone === 'error' ? 'alert' : 'status'}>
            <span>{t.message}</span>
            <button type="button" onClick={() => dismiss(t.id)}>Cerrar</button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): Notifier {
  const notify = useContext(ToastContext);
  if (!notify) throw new Error('useToast debe usarse dentro de ToastProvider');
  return notify;
}
