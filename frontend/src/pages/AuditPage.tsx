import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, keepPreviousData } from '@tanstack/react-query';
import { auditApi } from '../api/endpoints';
import type { AuditVerification } from '../api/types';
import { Badge, Empty, ErrorNotice, Loading, Notice, Pager, useToast } from '../components/ui';
import { formatDateTime } from '../lib/format';

const PER_PAGE = 25;

interface AuditFilters {
  q: string;
  case: string;
}

export function AuditPage() {
  const notify = useToast();
  const [draft, setDraft] = useState<AuditFilters>({ q: '', case: '' });
  const [filters, setFilters] = useState<AuditFilters>({ q: '', case: '' });
  const [page, setPage] = useState(1);
  const [verification, setVerification] = useState<AuditVerification | null>(null);

  const query = useQuery({
    queryKey: ['audit', filters, page],
    queryFn: () => auditApi.list({ q: filters.q || undefined, case: filters.case || undefined, page, per_page: PER_PAGE }),
    placeholderData: keepPreviousData,
  });

  const verify = useMutation({
    mutationFn: () => auditApi.verify(),
    onSuccess: (result) => setVerification(result),
    onError: () => notify('No pudimos verificar la cadena de auditoría.', 'error'),
  });

  const exportCsv = useMutation({
    mutationFn: () => auditApi.exportCsv(),
    onError: () => notify('No pudimos exportar la auditoría.', 'error'),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(1);
    setFilters({ q: draft.q.trim(), case: draft.case.trim() });
  }

  return (
    <>
      <header className="page-heading">
        <div>
          <div className="eyebrow">Auditoría</div>
          <h1>Registro de auditoría</h1>
          <p className="muted">Cada cambio queda registrado con quién lo hizo, cuándo y por qué.</p>
        </div>
        <div className="row">
          <button type="button" className="btn secondary" disabled={verify.isPending} onClick={() => verify.mutate()}>
            {verify.isPending ? 'Verificando…' : 'Verificar cadena'}
          </button>
          <button type="button" className="btn soft" disabled={exportCsv.isPending} onClick={() => exportCsv.mutate()}>
            Exportar CSV
          </button>
        </div>
      </header>

      <Notice tone="blue">El CSV exporta toda la bitácora, sin aplicar los filtros de esta pantalla.</Notice>

      {verification && (
        <div style={{ marginTop: 12 }}>
          {verification.ok ? (
            <Notice tone="green">
              Cadena íntegra: {verification.verified} registros verificados. {verification.notice}
            </Notice>
          ) : (
            <Notice tone="red">
              Se detectó una inconsistencia: {verification.failure ?? 'motivo no informado'}. {verification.notice}
            </Notice>
          )}
        </div>
      )}

      <form className="toolbar" role="search" noValidate onSubmit={submit} style={{ marginTop: 16 }}>
        <div className="field grow">
          <label htmlFor="audit-q">Buscar</label>
          <input id="audit-q" type="search" value={draft.q} onChange={(e) => setDraft({ ...draft, q: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="audit-case">Código de compra</label>
          <input id="audit-case" value={draft.case} onChange={(e) => setDraft({ ...draft, case: e.target.value })} placeholder="SC-2026-0001" />
        </div>
        <button type="submit" className="btn">Aplicar</button>
      </form>

      {query.isPending && <Loading />}
      {query.isError && <ErrorNotice error={query.error} />}
      {query.data && query.data.items.length === 0 && <Empty title="No hay registros para estos filtros." />}
      {query.data && query.data.items.length > 0 && (
        <>
          <div className="table-wrap" style={{ marginTop: 14 }}>
            <table>
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>Usuario</th>
                  <th>Acción</th>
                  <th>Recurso</th>
                  <th>Motivo</th>
                  <th>Huella</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((item) => (
                  <tr key={item.id}>
                    <td>{formatDateTime(item.at)}</td>
                    <td>{item.actor ?? '—'}{item.role ? <div className="small-text muted">{item.role}</div> : null}</td>
                    <td><Badge tone="blue">{item.action}</Badge></td>
                    <td>{item.resource_type}{item.resource_id ? ` · ${item.resource_id}` : ''}{item.version !== null ? ` · v${item.version}` : ''}</td>
                    <td className="small-text">{item.reason ?? '—'}</td>
                    <td className="table-id">{item.hash.slice(0, 12)}…</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager page={page} perPage={PER_PAGE} total={query.data.total} onPage={setPage} />
        </>
      )}
    </>
  );
}
