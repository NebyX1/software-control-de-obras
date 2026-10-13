import { useEffect, useState, type FormEvent } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { casesApi, organizationApi } from '../api/endpoints';
import { toApiError } from '../api/client';
import { Badge, Empty, ErrorNotice, Loading, Modal, Pager, useToast } from '../components/ui';
import { formatDate, formatMoney, uuid } from '../lib/format';
import { FILTER_OPTIONS, toneClass } from '../lib/labels';
import { useSession } from '../session';

const PER_PAGE = 10;

export function CasesPage() {
  const { can } = useSession();
  const [search, setSearch] = useState('');
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    const id = window.setTimeout(() => {
      setQ(search.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(id);
  }, [search]);

  const query = useQuery({
    queryKey: ['cases', { q, filter, page }],
    queryFn: () => casesApi.list({ q: q || undefined, filter, page, per_page: PER_PAGE }),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <header className="page-heading">
        <div>
          <div className="eyebrow">Compras</div>
          <h1>Compras</h1>
          <p className="muted">Solicitudes de compra con su expediente, etapa y responsables.</p>
        </div>
        {can('case.create') && (
          <button type="button" className="btn" onClick={() => setCreating(true)}>Nueva solicitud</button>
        )}
      </header>

      <div className="toolbar">
        <div className="searchbox">
          <label htmlFor="cases-search" className="sr-only">Buscar compras</label>
          <input
            id="cases-search"
            type="search"
            placeholder="Buscar por código, título o área"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <label htmlFor="cases-filter" className="sr-only">Filtrar compras</label>
        <select
          id="cases-filter"
          className="filter-select"
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value);
            setPage(1);
          }}
        >
          {FILTER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>

      {query.isPending && <Loading />}
      {query.isError && <ErrorNotice error={query.error} />}
      {query.data && (
        query.data.items.length === 0 ? (
          <Empty title="No hay compras que coincidan con la búsqueda.">
            Probá con otro término o cambiá el filtro.
          </Empty>
        ) : (
          <div className="card flat">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Código</th>
                    <th scope="col">Compra</th>
                    <th scope="col">Área</th>
                    <th scope="col">Etapa</th>
                    <th scope="col">Estado</th>
                    <th scope="col" className="num">Monto estimado</th>
                    <th scope="col">Actualizada</th>
                  </tr>
                </thead>
                <tbody>
                  {query.data.items.map((c) => (
                    <tr key={c.code}>
                      <td className="table-id">{c.code}</td>
                      <td>
                        <Link className="table-title" to={`/compras/${encodeURIComponent(c.code)}`}>{c.title}</Link>
                        {c.is_demo && <Badge tone="amber">Demo</Badge>}
                      </td>
                      <td>{c.area}</td>
                      <td>{c.stage_label}</td>
                      <td><Badge tone={toneClass(c.tone)}>{c.status_label}</Badge></td>
                      <td className="num">{formatMoney(c.estimated_total, c.currency)}</td>
                      <td>{formatDate(c.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="table-footer">
              <Pager page={page} perPage={PER_PAGE} total={query.data.total} onPage={setPage} />
            </div>
          </div>
        )
      )}

      {creating && <NewCaseModal onClose={() => setCreating(false)} />}
    </>
  );
}

interface LineDraft {
  description: string;
  quantity: string;
  unit: string;
  estimated_unit_price: string;
}

const EMPTY_LINE: LineDraft = { description: '', quantity: '', unit: 'unidad', estimated_unit_price: '' };

function normalizeDecimal(value: string): string {
  return value.trim().replace(',', '.');
}

function NewCaseModal({ onClose }: { onClose: () => void }) {
  const { user } = useSession();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const notify = useToast();
  const [idempotencyKey] = useState(() => uuid());
  const [title, setTitle] = useState('');
  const [needText, setNeedText] = useState('');
  const [areaId, setAreaId] = useState(user.area_id ? String(user.area_id) : '');
  const [estimatedTotal, setEstimatedTotal] = useState('');
  const [deliveryPlace, setDeliveryPlace] = useState('');
  const [lines, setLines] = useState<LineDraft[]>([{ ...EMPTY_LINE }]);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const areas = useQuery({ queryKey: ['areas'], queryFn: () => organizationApi.areas() });

  const mutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => casesApi.create(body, idempotencyKey),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ['cases'] });
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      notify(`Solicitud ${created.code} creada.`);
      onClose();
      navigate(`/compras/${encodeURIComponent(created.code)}`);
    },
    onError: (err) => {
      const apiErr = toApiError(err);
      setErrors(apiErr.fields ?? {});
    },
  });

  function updateLine(index: number, patch: Partial<LineDraft>) {
    setLines((prev) => prev.map((line, i) => (i === index ? { ...line, ...patch } : line)));
  }

  function validate(): Record<string, string> {
    const next: Record<string, string> = {};
    const t = title.trim();
    if (t.length < 5 || t.length > 200) next.title = 'Entre 5 y 200 caracteres.';
    if (needText.trim().length < 10) next.need_text = 'Describí la necesidad con al menos 10 caracteres.';
    if (!areaId) next.area_id = 'Elegí un área.';
    const total = Number(normalizeDecimal(estimatedTotal));
    if (!normalizeDecimal(estimatedTotal) || !Number.isFinite(total) || total <= 0) {
      next.estimated_total = 'Ingresá un monto mayor que cero.';
    }
    if (lines.length < 1) next.lines = 'Agregá al menos un renglón.';
    lines.forEach((line, i) => {
      if (!line.description.trim()) next[`lines.${i}.description`] = 'Describí el bien o servicio.';
      const qty = Number(normalizeDecimal(line.quantity));
      if (!normalizeDecimal(line.quantity) || !Number.isFinite(qty) || qty <= 0) {
        next[`lines.${i}.quantity`] = 'Cantidad mayor que cero.';
      }
      if (!line.unit.trim()) next[`lines.${i}.unit`] = 'Indicá la unidad de medida.';
    });
    return next;
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    mutation.mutate({
      title: title.trim(),
      need_text: needText.trim(),
      area_id: Number(areaId),
      estimated_total: normalizeDecimal(estimatedTotal),
      delivery_place: deliveryPlace.trim() || undefined,
      currency: 'UYU',
      lines: lines.map((line) => ({
        description: line.description.trim(),
        quantity: normalizeDecimal(line.quantity),
        unit: line.unit.trim(),
        estimated_unit_price: line.estimated_unit_price.trim() ? normalizeDecimal(line.estimated_unit_price) : undefined,
      })),
    });
  }

  const apiError = mutation.isError ? toApiError(mutation.error) : null;
  const fieldError = (key: string) => errors[key] ?? '';

  return (
    <Modal
      title="Nueva solicitud de compra"
      wide
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn secondary" onClick={onClose}>Cancelar</button>
          <button type="submit" form="new-case-form" className="btn" disabled={mutation.isPending}>
            {mutation.isPending ? 'Creando…' : 'Crear solicitud'}
          </button>
        </>
      }
    >
      <form id="new-case-form" className="stack" noValidate onSubmit={submit}>
        {apiError && !apiError.fields?.title && <ErrorNotice error={mutation.error} />}
        <div className="field">
          <label htmlFor="nc-title">Título <span className="req">*</span></label>
          <input id="nc-title" value={title} onChange={(e) => setTitle(e.target.value)} aria-invalid={fieldError('title') ? 'true' : undefined} />
          <div className="form-error">{fieldError('title')}</div>
        </div>
        <div className="field">
          <label htmlFor="nc-need">Necesidad <span className="req">*</span></label>
          <textarea id="nc-need" value={needText} onChange={(e) => setNeedText(e.target.value)} aria-invalid={fieldError('need_text') ? 'true' : undefined} />
          <div className="field-help">Qué se necesita, para qué y en qué condiciones.</div>
          <div className="form-error">{fieldError('need_text')}</div>
        </div>
        <div className="fields-2">
          <div className="field">
            <label htmlFor="nc-area">Área <span className="req">*</span></label>
            {areas.isError ? (
              <ErrorNotice error={areas.error} />
            ) : (
              <select id="nc-area" value={areaId} onChange={(e) => setAreaId(e.target.value)} aria-invalid={fieldError('area_id') ? 'true' : undefined}>
                <option value="">Elegí un área</option>
                {(areas.data?.items ?? []).map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
            )}
            <div className="form-error">{fieldError('area_id')}</div>
          </div>
          <div className="field">
            <label htmlFor="nc-total">Monto estimado total (UYU) <span className="req">*</span></label>
            <input id="nc-total" inputMode="decimal" placeholder="0,00" value={estimatedTotal} onChange={(e) => setEstimatedTotal(e.target.value)} aria-invalid={fieldError('estimated_total') ? 'true' : undefined} />
            <div className="form-error">{fieldError('estimated_total')}</div>
          </div>
        </div>
        <div className="field">
          <label htmlFor="nc-place">Lugar de entrega</label>
          <input id="nc-place" value={deliveryPlace} onChange={(e) => setDeliveryPlace(e.target.value)} />
        </div>

        <fieldset className="spec-block" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="section-label">Renglones</legend>
          {lines.map((line, i) => (
            <div key={i} className="line-row">
              <div className="line-row-head">
                <strong>Renglón {i + 1}</strong>
                {lines.length > 1 && (
                  <button type="button" className="text-btn" onClick={() => setLines((prev) => prev.filter((_, idx) => idx !== i))}>Quitar</button>
                )}
              </div>
              <div className="field">
                <label htmlFor={`nc-line-${i}-desc`}>Descripción <span className="req">*</span></label>
                <input id={`nc-line-${i}-desc`} value={line.description} onChange={(e) => updateLine(i, { description: e.target.value })} aria-invalid={fieldError(`lines.${i}.description`) ? 'true' : undefined} />
                <div className="form-error">{fieldError(`lines.${i}.description`)}</div>
              </div>
              <div className="fields-2">
                <div className="field">
                  <label htmlFor={`nc-line-${i}-qty`}>Cantidad <span className="req">*</span></label>
                  <input id={`nc-line-${i}-qty`} inputMode="decimal" value={line.quantity} onChange={(e) => updateLine(i, { quantity: e.target.value })} aria-invalid={fieldError(`lines.${i}.quantity`) ? 'true' : undefined} />
                  <div className="form-error">{fieldError(`lines.${i}.quantity`)}</div>
                </div>
                <div className="field">
                  <label htmlFor={`nc-line-${i}-unit`}>Unidad <span className="req">*</span></label>
                  <input id={`nc-line-${i}-unit`} value={line.unit} onChange={(e) => updateLine(i, { unit: e.target.value })} aria-invalid={fieldError(`lines.${i}.unit`) ? 'true' : undefined} />
                  <div className="form-error">{fieldError(`lines.${i}.unit`)}</div>
                </div>
              </div>
              <div className="field">
                <label htmlFor={`nc-line-${i}-price`}>Precio unitario estimado (opcional)</label>
                <input id={`nc-line-${i}-price`} inputMode="decimal" value={line.estimated_unit_price} onChange={(e) => updateLine(i, { estimated_unit_price: e.target.value })} />
              </div>
            </div>
          ))}
          <div className="form-error">{fieldError('lines')}</div>
          <div>
            <button type="button" className="btn soft small" onClick={() => setLines((prev) => [...prev, { ...EMPTY_LINE }])} disabled={lines.length >= 100}>
              Agregar renglón
            </button>
          </div>
        </fieldset>
      </form>
    </Modal>
  );
}
