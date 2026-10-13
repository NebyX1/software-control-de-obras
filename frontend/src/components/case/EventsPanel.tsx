import { useInfiniteQuery } from '@tanstack/react-query';
import { casesApi } from '../../api/endpoints';
import type { EventJson } from '../../api/types';
import { ErrorNotice, Loading, Notice } from '../ui';
import { formatDateTime } from '../../lib/format';

const PAGE_SIZE = 50;

export function EventsPanel({ code }: { code: string }) {
  const query = useInfiniteQuery({
    queryKey: ['case-events', code],
    queryFn: ({ pageParam }) => casesApi.events(code, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (lastPage: { items: EventJson[] }) =>
      lastPage.items.length === PAGE_SIZE ? lastPage.items[lastPage.items.length - 1].id : undefined,
  });

  const events = query.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <>
      <h3 className="section-label">Bitácora</h3>
      {query.isPending && <Loading label="Cargando la bitácora…" />}
      {query.isError && <ErrorNotice error={query.error} />}
      {query.data && events.length === 0 && <p className="muted">Todavía no hay movimientos registrados.</p>}
      {events.length > 0 && (
        <ol className="helper-list" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {events.map((e) => (
            <li key={e.id} className="activity-line">
              <div>
                <strong>{e.action}</strong>
                {e.reason && <span className="muted"> · {e.reason}</span>}
              </div>
              <div className="small-text muted">
                {formatDateTime(e.at)}{e.actor ? ` · ${e.actor}` : ''}{e.role ? ` (${e.role})` : ''}
              </div>
            </li>
          ))}
        </ol>
      )}
      {query.hasNextPage && (
        <div style={{ marginTop: 10 }}>
          <button
            type="button"
            className="btn secondary small"
            disabled={query.isFetchingNextPage}
            onClick={() => void query.fetchNextPage()}
          >
            {query.isFetchingNextPage ? 'Cargando…' : 'Cargar más'}
          </button>
        </div>
      )}
    </>
  );
}

export function AiPanel() {
  return (
    <div className="card flat" style={{ marginTop: 18 }}>
      <h3 className="section-label">Asistente de IA</h3>
      <Notice tone="blue">
        La asistencia de IA no está disponible en este entorno. Las acciones de IA quedan deshabilitadas hasta que el
        administrador la active y configure un modelo válido. Ningún resultado de IA reemplaza la decisión humana.
      </Notice>
      <div className="row" style={{ marginTop: 10 }}>
        <button type="button" className="btn soft small" disabled>Extraer datos de una oferta</button>
        <button type="button" className="btn soft small" disabled>Explicar el expediente</button>
        <button type="button" className="btn soft small" disabled>Buscar inconsistencias</button>
      </div>
    </div>
  );
}
