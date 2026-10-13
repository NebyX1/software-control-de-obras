import { useQueries } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { casesApi } from '../api/endpoints';
import type { CaseSummary } from '../api/types';
import { Badge, Empty, ErrorNotice, Loading } from '../components/ui';
import { formatMoney } from '../lib/format';
import { STAGE_LABELS } from '../lib/labels';

// Etapas 2 (Ofertas), 3 (Evaluación) y 4 (Decisión), índices según STAGE_LABELS.
const EVALUATION_STAGES = [2, 3, 4];

export function EvaluatePage() {
  const results = useQueries({
    queries: EVALUATION_STAGES.map((stage) => ({
      queryKey: ['cases', { filter: 'active', stage, per_page: 50 }],
      queryFn: () => casesApi.list({ filter: 'active', stage, per_page: 50 }),
    })),
  });

  const loading = results.some((r) => r.isPending);
  const failed = results.find((r) => r.isError);
  const cases: CaseSummary[] = results.flatMap((r) => r.data?.items ?? []);
  const truncated = results.some((r) => (r.data?.total ?? 0) > (r.data?.items.length ?? 0));

  return (
    <>
      <header className="page-heading">
        <div>
          <div className="eyebrow">Evaluación</div>
          <h1>Ofertas por comparar</h1>
          <p className="muted">
            Compras con ofertas, en evaluación o en decisión. La recomendación no es una adjudicación.
          </p>
        </div>
      </header>

      {loading && <Loading />}
      {failed && failed.error && <ErrorNotice error={failed.error} />}
      {!loading && !failed && cases.length === 0 && (
        <Empty title="No hay compras en evaluación.">
          Cuando una compra tenga ofertas registradas aparecerá aquí.
        </Empty>
      )}
      {!loading && cases.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Compra</th>
                <th>Etapa</th>
                <th>Estado</th>
                <th className="num">Monto estimado</th>
                <th><span className="sr-only">Acciones</span></th>
              </tr>
            </thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.code}>
                  <td>
                    <div className="table-id">{c.code}</div>
                    <div className="table-title">{c.title}</div>
                  </td>
                  <td>{STAGE_LABELS[c.stage] ?? c.stage_label}</td>
                  <td><Badge tone={c.tone}>{c.status_label}</Badge></td>
                  <td className="num">{c.estimated_total ? formatMoney(c.estimated_total, c.currency) : '—'}</td>
                  <td>
                    <Link to={`/compras/${encodeURIComponent(c.code)}`}>Abrir evaluación</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {truncated && (
        <p className="small-text muted" style={{ marginTop: 10 }}>
          Se muestran las primeras 50 compras por etapa. Usá el listado de compras para ver el resto.
        </p>
      )}
    </>
  );
}
