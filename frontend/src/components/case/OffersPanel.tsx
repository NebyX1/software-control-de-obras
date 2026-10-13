import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { casesApi } from '../../api/endpoints';
import type { Evaluation, EvaluationOfferResult, Offer } from '../../api/types';
import { Badge, Empty, ErrorNotice, Loading, Modal, Notice } from '../ui';
import { formatMoney } from '../../lib/format';

const STATUS_TONE: Record<string, string> = {
  admissible: 'green',
  excluded: 'red',
  pending: 'amber',
};

function byRank(a: EvaluationOfferResult, b: EvaluationOfferResult) {
  if (a.rank === null && b.rank === null) return a.name.localeCompare(b.name);
  if (a.rank === null) return 1;
  if (b.rank === null) return -1;
  return a.rank - b.rank;
}

export function OffersPanel({
  code,
  offers,
  offersSealed,
  evaluation,
}: {
  code: string;
  offers: Offer[];
  offersSealed: boolean;
  evaluation: Evaluation | null;
}) {
  const [explaining, setExplaining] = useState(false);
  const recommendedId = evaluation?.recommended_offer_id ?? null;
  const evalOffers = [...(evaluation?.result?.offers ?? [])].sort(byRank);

  return (
    <>
      <h3 className="section-label">Ofertas</h3>
      {offersSealed && (
        <Notice tone="amber">Las ofertas están selladas. Los precios se revelan al abrir el sobre.</Notice>
      )}
      {offers.length === 0 ? (
        <Empty title="Todavía no hay ofertas registradas." />
      ) : (
        <div className="offer-cards">
          {offers.map((offer) => (
            <div key={offer.id} className={`offer-card${offer.id === recommendedId ? ' best' : ''}`}>
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <strong>{offer.supplier}</strong>
                <Badge tone={offer.status === 'recorded' ? 'green' : 'neutral'}>{offer.status}</Badge>
              </div>
              {offer.data ? (
                <div className="small-text muted">
                  {offer.data.prices_include_tax ? 'Precios con impuestos' : 'Precios sin impuestos'}
                  {offer.data.delivery_days !== null && ` · Entrega ${offer.data.delivery_days} días`}
                  {offer.data.warranty_months !== null && ` · Garantía ${offer.data.warranty_months} meses`}
                  {offer.data.freight !== null && ` · Flete ${formatMoney(offer.data.freight, offer.currency)}`}
                </div>
              ) : (
                <div className="small-text muted">{offersSealed ? 'Oferta sellada.' : 'Sin datos de precio registrados.'}</div>
              )}
              {offer.id === recommendedId && <Badge tone="purple">Recomendada</Badge>}
            </div>
          ))}
        </div>
      )}

      <div className="row" style={{ justifyContent: 'space-between', margin: '22px 0 10px' }}>
        <h3 className="section-label" style={{ margin: 0 }}>Evaluación</h3>
        {evaluation && (
          <button type="button" className="btn secondary small" onClick={() => setExplaining(true)}>
            Ver cálculo
          </button>
        )}
      </div>

      {!evaluation ? (
        <Empty title="Todavía no hay evaluación para esta compra." />
      ) : (
        <>
          {evaluation.stale_reason && (
            <Notice tone="amber">La evaluación está desactualizada: {evaluation.stale_reason}</Notice>
          )}
          {evalOffers.length === 0 ? (
            <Empty title="La evaluación no tiene resultados por oferta." />
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th className="num">Puesto</th>
                    <th>Oferta</th>
                    <th>Estado</th>
                    <th className="num">Comercial</th>
                    <th className="num">Comparable</th>
                    <th className="num">Puntaje</th>
                    <th>Motivos</th>
                  </tr>
                </thead>
                <tbody>
                  {evalOffers.map((o) => (
                    <tr key={o.id} className={o.id === recommendedId ? 'best' : undefined}>
                      <td className="num">{o.rank ?? '—'}</td>
                      <td className="table-title">{o.name}</td>
                      <td><Badge tone={STATUS_TONE[o.status] ?? 'neutral'}>{o.status}</Badge></td>
                      <td className="num">{o.totals?.commercial ? formatMoney(o.totals.commercial, o.totals.currency) : '—'}</td>
                      <td className="num">{o.totals?.comparable ? formatMoney(o.totals.comparable, o.totals.currency) : '—'}</td>
                      <td className="num">{o.score_display ?? '—'}</td>
                      <td className="small-text">
                        {[...o.reasons, ...o.pending, ...o.warnings].join(' · ') || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="small-text muted" style={{ marginTop: 10 }}>
            La recomendación no es una adjudicación. La decisión la toma el responsable autorizado.
          </p>
        </>
      )}

      {explaining && <ExplanationModal code={code} onClose={() => setExplaining(false)} />}
    </>
  );
}

function ExplanationModal({ code, onClose }: { code: string; onClose: () => void }) {
  const query = useQuery({
    queryKey: ['case-explanation', code],
    queryFn: () => casesApi.explanation(code),
  });

  return (
    <Modal title="El cálculo, abierto" onClose={onClose} wide>
      {query.isPending && <Loading label="Cargando el cálculo…" />}
      {query.isError && <ErrorNotice error={query.error} />}
      {query.data && (
        <div className="stack">
          <div>
            <strong>{query.data.title}</strong>
            <div className="small-text muted">{query.data.source}</div>
          </div>
          {query.data.sections.map((section) => (
            <div key={section.heading}>
              <h4 className="section-label">{section.heading}</h4>
              <ul className="helper-list">
                {section.items.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
