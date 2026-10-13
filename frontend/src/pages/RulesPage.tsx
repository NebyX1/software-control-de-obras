import { useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { rulesApi } from '../api/endpoints';
import { Badge, Empty, ErrorNotice, Loading, Notice } from '../components/ui';
import { formatDate } from '../lib/format';

const AMOUNT_PATTERN = /^\d+(\.\d{1,2})?$/;

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
}

export function RulesPage() {
  const rules = useQuery({ queryKey: ['rules'], queryFn: () => rulesApi.rules() });

  return (
    <>
      <header className="page-heading">
        <div>
          <div className="eyebrow">Reglas</div>
          <h1>Reglas y fuentes oficiales</h1>
          <p className="muted">Consulta de las reglas activas, sugerencias por monto y fuentes normativas.</p>
        </div>
      </header>

      {rules.isPending && <Loading />}
      {rules.isError && <ErrorNotice error={rules.error} />}
      {rules.data && (
        <>
          <Notice tone="blue">{rules.data.notice}</Notice>
          <div className="two-col" style={{ marginTop: 18 }}>
            <section className="card flat" aria-labelledby="rules-active">
              <div className="card-head">
                <h2 id="rules-active">Reglas activas</h2>
              </div>
              {rules.data.active ? (
                <div className="table-wrap">
                  <table>
                    <tbody>
                      {Object.entries(rules.data.active).map(([key, value]) => (
                        <tr key={key}>
                          <th scope="row">{key}</th>
                          <td>
                            {typeof value === 'object' && value !== null ? <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{renderValue(value)}</pre> : renderValue(value)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty title="No hay un conjunto de reglas activo." />
              )}
            </section>

            <section className="card flat" aria-labelledby="rules-versions">
              <div className="card-head">
                <h2 id="rules-versions">Versiones</h2>
              </div>
              {rules.data.versions.length === 0 ? (
                <Empty title="No hay versiones registradas." />
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Código</th>
                        <th>Estado</th>
                        <th>Vigente desde</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rules.data.versions.map((v) => (
                        <tr key={v.code}>
                          <td>{v.code}</td>
                          <td><Badge tone={v.status === 'active' ? 'green' : 'neutral'}>{v.status}</Badge></td>
                          <td>{formatDate(v.valid_from)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        </>
      )}

      <SuggestSection />
      <NormativeSection />
    </>
  );
}

function SuggestSection() {
  const [draft, setDraft] = useState('');
  const [amount, setAmount] = useState<string | null>(null);
  const [invalid, setInvalid] = useState(false);

  const query = useQuery({
    queryKey: ['rules-suggest', amount],
    queryFn: () => rulesApi.suggest(amount ?? ''),
    enabled: amount !== null,
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = draft.trim();
    if (!AMOUNT_PATTERN.test(value)) {
      setInvalid(true);
      setAmount(null);
      return;
    }
    setInvalid(false);
    setAmount(value);
  }

  return (
    <section className="card flat" aria-labelledby="rules-suggest" style={{ marginTop: 18 }}>
      <div className="card-head">
        <h2 id="rules-suggest">Sugerencia por monto</h2>
      </div>
      <form className="row" noValidate onSubmit={submit}>
        <div className="field grow">
          <label htmlFor="suggest-amount">Monto estimado (UYU)</label>
          <input
            id="suggest-amount"
            inputMode="decimal"
            value={draft}
            aria-invalid={invalid ? 'true' : undefined}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Ej.: 120000.00"
          />
          <div className="form-error">{invalid ? 'Ingresá un monto válido, con punto para los decimales.' : ''}</div>
        </div>
        <button type="submit" className="btn">Consultar</button>
      </form>
      {query.isFetching && <Loading label="Consultando…" />}
      {query.isError && <ErrorNotice error={query.error} />}
      {query.data && !query.isFetching && (
        <pre style={{ whiteSpace: 'pre-wrap', marginTop: 12 }}>{JSON.stringify(query.data, null, 2)}</pre>
      )}
    </section>
  );
}

function NormativeSection() {
  const [draft, setDraft] = useState('');
  const [term, setTerm] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ['normative', term],
    queryFn: () => rulesApi.normative(term ?? ''),
    enabled: term !== null,
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTerm(draft.trim());
  }

  return (
    <section className="card flat" aria-labelledby="rules-normative" style={{ marginTop: 18 }}>
      <div className="card-head">
        <h2 id="rules-normative">Biblioteca de fuentes oficiales</h2>
      </div>
      <form className="row" role="search" noValidate onSubmit={submit}>
        <div className="field grow">
          <label htmlFor="normative-q">Buscar en las fuentes</label>
          <input id="normative-q" type="search" value={draft} onChange={(e) => setDraft(e.target.value)} />
        </div>
        <button type="submit" className="btn">Buscar</button>
      </form>
      {query.isFetching && <Loading label="Buscando…" />}
      {query.isError && <ErrorNotice error={query.error} />}
      {query.data && !query.isFetching && (
        <div className="stack" style={{ marginTop: 12 }}>
          <Notice tone="blue">{query.data.notice}</Notice>
          {query.data.items.length === 0 ? (
            <Empty title="No encontramos fuentes para esa búsqueda." />
          ) : (
            query.data.items.map((s) => (
              <article key={`${s.code}-${s.url}`} className="doc">
                <div className="grow">
                  <strong>{s.titulo}</strong>
                  <div className="small-text muted">{s.organismo} · {s.consulta}</div>
                  <p>{s.hallazgo}</p>
                  <Badge tone={s.validation_status === 'validated' ? 'green' : 'amber'}>{s.validation_status}</Badge>
                </div>
                {s.url.startsWith('https://') ? (
                  <a className="btn secondary small" href={s.url} target="_blank" rel="noopener noreferrer">Abrir fuente</a>
                ) : (
                  <span className="small-text muted">Sin enlace seguro</span>
                )}
              </article>
            ))
          )}
        </div>
      )}
    </section>
  );
}
