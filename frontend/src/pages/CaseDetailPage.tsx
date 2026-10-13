import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { casesApi } from '../api/endpoints';
import { Badge, Empty, ErrorNotice, Loading, Notice } from '../components/ui';
import { ActionsPanel } from '../components/case/ActionsPanel';
import { AiPanel, EventsPanel } from '../components/case/EventsPanel';
import { DocumentsPanel } from '../components/case/DocumentsPanel';
import { OffersPanel } from '../components/case/OffersPanel';
import { formatMoney, joinResponsible } from '../lib/format';
import { PROCEDURE_MODE_LABELS, STAGE_LABELS } from '../lib/labels';

export function CaseDetailPage() {
  const { code = '' } = useParams();
  const query = useQuery({
    queryKey: ['case', code],
    queryFn: () => casesApi.get(code),
    enabled: code !== '',
  });

  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorNotice error={query.error} />;

  const c = query.data;
  const stages = c.stages.length > 0 ? c.stages : STAGE_LABELS;

  return (
    <>
      <nav className="small-text" aria-label="Migas de pan" style={{ marginBottom: 8 }}>
        <Link to="/compras">← Volver a compras</Link>
      </nav>

      <header className="page-heading">
        <div>
          <div className="eyebrow">{c.code}</div>
          <h1>{c.title}</h1>
          <p className="muted">
            {c.area} · {c.procedure_label} · {c.estimated_total ? `Monto estimado ${formatMoney(c.estimated_total, c.currency)}` : 'Sin monto estimado'}
          </p>
        </div>
        <div className="row">
          <Badge tone={c.tone}>{c.status_label}</Badge>
          {c.is_demo && <Badge tone="amber">Datos de prueba</Badge>}
        </div>
      </header>

      <ol className="stepper" aria-label="Etapas de la compra">
        {stages.map((label, i) => {
          const cls = i < c.stage ? 'step done' : i === c.stage ? 'step now' : 'step';
          return (
            <li key={label} className={cls} aria-current={i === c.stage ? 'step' : undefined}>
              <b>{i + 1}</b>
              {label}
            </li>
          );
        })}
      </ol>

      {c.next && (
        <section className="card next-card" aria-label="Siguiente paso" style={{ marginBottom: 18 }}>
          <div className="eyebrow">Siguiente paso</div>
          <strong>{c.next.label}</strong>
          <div className="small-text muted">Responsable: {joinResponsible(c.next.responsible)}</div>
          {c.next.blockers.length > 0 && (
            <Notice tone="amber">Pendiente: {c.next.blockers.join(' · ')}</Notice>
          )}
        </section>
      )}

      <div className="case-grid">
        <div className="stack">
          <section className="card flat" aria-labelledby="case-actions">
            <div className="card-head">
              <h2 id="case-actions">Acciones</h2>
            </div>
            <ActionsPanel code={c.code} version={c.version} actions={c.actions} documents={c.documents} />
          </section>

          <section className="card flat" aria-labelledby="case-spec">
            <div className="card-head">
              <h2 id="case-spec">Especificación</h2>
            </div>
            {c.spec ? (
              <div className="stack">
                <div className="small-text muted">
                  Versión {c.spec.version} · {PROCEDURE_MODE_LABELS[c.spec.mode] ?? c.spec.mode} · {c.spec.status}
                </div>
                {c.spec.minimum_text && <p>{c.spec.minimum_text}</p>}
                {c.spec.requirements.length > 0 && (
                  <div>
                    <h3 className="section-label">Requisitos</h3>
                    <ul className="helper-list">
                      {c.spec.requirements.map((r) => (
                        <li key={r.code}>
                          <strong>{r.code}</strong> {r.text}{r.essential ? ' (excluyente)' : ''}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {c.spec.criteria.length > 0 && (
                  <div>
                    <h3 className="section-label">Criterios</h3>
                    <ul className="helper-list">
                      {c.spec.criteria.map((k) => (
                        <li key={k.code}>
                          <strong>{k.name}</strong> · peso {k.weight}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              <Empty title="La especificación todavía no está definida." />
            )}
          </section>

          <section className="card flat" aria-labelledby="case-offers">
            <div className="card-head">
              <h2 id="case-offers">Ofertas y evaluación</h2>
            </div>
            <OffersPanel code={c.code} offers={c.offers} offersSealed={c.offers_sealed} evaluation={c.evaluation} />
          </section>

          <section className="card flat" aria-labelledby="case-docs">
            <div className="card-head">
              <h2 id="case-docs">Documentos</h2>
            </div>
            <DocumentsPanel code={c.code} documents={c.documents} />
          </section>
        </div>

        <aside className="stack">
          <section className="card flat" aria-labelledby="case-lines">
            <div className="card-head">
              <h2 id="case-lines">Renglones</h2>
            </div>
            {c.lines.length === 0 ? (
              <Empty title="Esta compra no tiene renglones." />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Descripción</th>
                      <th className="num">Cant.</th>
                      <th>Unidad</th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.lines.map((line) => (
                      <tr key={line.id}>
                        <td>{line.description}</td>
                        <td className="num">{line.quantity}</td>
                        <td>{line.unit}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="card flat" aria-labelledby="case-events">
            <EventsPanel code={c.code} />
          </section>

          <AiPanel />
        </aside>
      </div>
    </>
  );
}
