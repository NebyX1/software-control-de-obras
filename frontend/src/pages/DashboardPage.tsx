import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { casesApi } from '../api/endpoints';
import { Badge, Empty, ErrorNotice, Loading, Stat } from '../components/ui';
import { formatDateTime, formatMoney } from '../lib/format';
import { toneClass } from '../lib/labels';
import { useSession } from '../session';

export function DashboardPage() {
  const { user } = useSession();
  const query = useQuery({ queryKey: ['dashboard'], queryFn: () => casesApi.dashboard() });

  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorNotice error={query.error} />;

  const data = query.data;
  const first = user.full_name.split(' ')[0] ?? user.full_name;

  return (
    <>
      <header className="page-heading">
        <div>
          <div className="eyebrow">Escritorio</div>
          <h1>Compras en movimiento</h1>
          <p className="muted">Hola, {first}. Estas son las compras que siguen abiertas y lo que necesitan de vos.</p>
        </div>
      </header>

      <section className="stats-grid" aria-label="Resumen">
        <Stat label="Compras activas" value={data.stats.active} glyph="◎" tone="blue" />
        <Stat label="Listas para comparar" value={data.stats.ready_to_compare} glyph="⇄" tone="green" />
        <Stat label="Necesitan atención" value={data.stats.attention} glyph="!" tone="amber" />
        <Stat label="Eventos registrados" value={data.stats.events} glyph="≡" />
      </section>

      <div className="two-col" style={{ marginTop: 18 }}>
        <section className="card flat" aria-labelledby="dash-cases">
          <div className="card-head">
            <h2 id="dash-cases">Compras</h2>
            <Link className="text-btn" to="/compras">Ver todas</Link>
          </div>
          {data.cases.length === 0 ? (
            <Empty title="Todavía no hay compras visibles para tu rol." />
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Código</th>
                    <th scope="col">Compra</th>
                    <th scope="col">Etapa</th>
                    <th scope="col">Estado</th>
                    <th scope="col" className="num">Monto estimado</th>
                  </tr>
                </thead>
                <tbody>
                  {data.cases.map((c) => (
                    <tr key={c.code}>
                      <td className="table-id">{c.code}</td>
                      <td>
                        <Link className="table-title" to={`/compras/${encodeURIComponent(c.code)}`}>{c.title}</Link>
                        {c.is_demo && <Badge tone="amber">Demo</Badge>}
                      </td>
                      <td>{c.stage_label}</td>
                      <td><Badge tone={toneClass(c.tone)}>{c.status_label}</Badge></td>
                      <td className="num">{formatMoney(c.estimated_total, c.currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="card flat" aria-labelledby="dash-activity">
          <div className="card-head">
            <h2 id="dash-activity">Actividad reciente</h2>
          </div>
          {data.recent.length === 0 ? (
            <Empty title="Sin actividad todavía." />
          ) : (
            <ul className="stack" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {data.recent.map((e) => (
                <li key={e.id} className="activity-line">
                  <div><strong>{e.action}</strong>{e.reason ? ` · ${e.reason}` : ''}</div>
                  <div className="small-text muted">
                    {formatDateTime(e.at)}{e.actor ? ` · ${e.actor}` : ''}{e.resource_id ? ` · ${e.resource_type} ${e.resource_id}` : ''}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
