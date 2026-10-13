import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { adminApi, organizationApi } from '../api/endpoints';
import { toApiError } from '../api/client';
import type { AdminAssignment, AdminRole, AdminUser, Area, SegregationRule } from '../api/types';
import { Badge, Empty, ErrorNotice, Loading, Modal, Notice, useToast } from '../components/ui';
import { useSession } from '../session';
import { formatDateTime } from '../lib/format';

type TabKey = 'users' | 'areas' | 'segregation' | 'holidays';

const TABS: { key: TabKey; label: string; permission: string }[] = [
  { key: 'users', label: 'Usuarios', permission: 'admin.users' },
  { key: 'areas', label: 'Áreas', permission: 'admin.areas' },
  { key: 'segregation', label: 'Segregación de funciones', permission: 'admin.users' },
  { key: 'holidays', label: 'Feriados', permission: 'admin.rules' },
];

const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const DECIMAL_PATTERN = /^\d+(\.\d{1,2})?$/;

function normalizeDecimal(value: string): string {
  return value.trim().replace(',', '.');
}

interface IssuedPassword {
  username: string;
  password: string;
}

export function AdminPage() {
  const { can } = useSession();
  const visible = TABS.filter((tab) => can(tab.permission));
  const [selected, setSelected] = useState<TabKey | null>(null);

  if (visible.length === 0) return <Empty title="No tenés permisos de administración." />;

  const current = visible.find((tab) => tab.key === selected)?.key ?? visible[0].key;

  return (
    <>
      <header className="page-heading">
        <div>
          <div className="eyebrow">Administración</div>
          <h1>Administración</h1>
          <p className="muted">Accesos, áreas, competencias y reglas de segregación. La cuenta de administración no adquiere competencia para adjudicar, autorizar ni pagar.</p>
        </div>
      </header>

      <div className="pill-tabs" role="group" aria-label="Secciones de administración" style={{ marginBottom: 16 }}>
        {visible.map((tab) => (
          <button key={tab.key} type="button" aria-pressed={current === tab.key} onClick={() => setSelected(tab.key)}>
            {tab.label}
          </button>
        ))}
      </div>

      {current === 'users' && <UsersTab />}
      {current === 'areas' && <AreasTab />}
      {current === 'segregation' && <SegregationTab />}
      {current === 'holidays' && <HolidaysTab />}
    </>
  );
}

function useAreas() {
  return useQuery({ queryKey: ['areas'], queryFn: () => organizationApi.areas() });
}

function UsersTab() {
  const { user: me } = useSession();
  const notify = useToast();
  const queryClient = useQueryClient();
  const areas = useAreas();
  const [creating, setCreating] = useState(false);
  const [assigning, setAssigning] = useState<AdminUser | null>(null);
  const [revoking, setRevoking] = useState<{ user: AdminUser; assignment: AdminAssignment } | null>(null);
  const [issued, setIssued] = useState<IssuedPassword | null>(null);

  const query = useQuery({ queryKey: ['admin-users'], queryFn: () => adminApi.users() });

  const patch = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) => adminApi.patchUser(id, body),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ['admin-users'] });
      if (result.temporary_password) {
        setIssued({ username: result.user.username, password: result.temporary_password });
      } else {
        notify('Cambios guardados.');
      }
    },
    onError: (err) => notify(toApiError(err).message, 'error'),
  });

  function resetPassword(user: AdminUser) {
    if (!window.confirm(`Se generará una contraseña temporal nueva para ${user.full_name}. Las sesiones activas de esa cuenta se cerrarán. ¿Continuar?`)) return;
    patch.mutate({ id: user.id, body: { reset_password: true } });
  }

  const areaNames = new Map((areas.data?.items ?? []).map((a) => [a.id, a.name]));
  const roles = query.data?.roles ?? [];

  return (
    <>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
        <span className="muted small-text">{query.data ? `${query.data.items.length} usuarios` : ''}</span>
        <button type="button" className="btn" onClick={() => setCreating(true)}>Nuevo usuario</button>
      </div>

      {query.isPending && <Loading />}
      {query.isError && <ErrorNotice error={query.error} />}
      {query.data && query.data.items.length === 0 && <Empty title="No hay usuarios cargados." />}
      {query.data && query.data.items.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Persona</th>
                <th>Estado</th>
                <th>Roles vigentes</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {query.data.items.map((u) => {
                const liveAssignments = u.assignments.filter((a) => !a.revoked);
                const isMe = u.id === me.id;
                return (
                  <tr key={u.id}>
                    <td>
                      <div className="table-title">{u.full_name}</div>
                      <div className="small-text muted">{u.username} · {u.email}</div>
                    </td>
                    <td>
                      <div className="row">
                        <Badge tone={u.active ? 'green' : 'neutral'}>{u.active ? 'Activo' : 'Inactivo'}</Badge>
                        {u.locked && <Badge tone="red">Bloqueado</Badge>}
                        {u.is_demo && <Badge tone="amber">Demo</Badge>}
                      </div>
                    </td>
                    <td>
                      {liveAssignments.length === 0 && <span className="muted small-text">Sin roles vigentes</span>}
                      <div className="stack">
                        {liveAssignments.map((a) => (
                          <div key={a.id} className="row small-text">
                            <span>
                              {a.role_name ?? a.role}
                              {a.area_id ? ` · ${areaNames.get(a.area_id) ?? `área ${a.area_id}`}` : ''}
                              {a.valid_to ? ` · hasta ${formatDateTime(a.valid_to)}` : ''}
                            </span>
                            <button type="button" className="text-btn" onClick={() => setRevoking({ user: u, assignment: a })}>Revocar</button>
                          </div>
                        ))}
                      </div>
                    </td>
                    <td>
                      <div className="row">
                        <button
                          type="button"
                          className={`btn small ${u.active ? 'danger' : 'success'}`}
                          disabled={patch.isPending || (isMe && u.active)}
                          title={isMe && u.active ? 'No podés desactivar tu propia cuenta.' : undefined}
                          onClick={() => patch.mutate({ id: u.id, body: { active: !u.active } })}
                        >
                          {u.active ? 'Desactivar' : 'Activar'}
                        </button>
                        {u.locked && (
                          <button type="button" className="btn small soft" disabled={patch.isPending} onClick={() => patch.mutate({ id: u.id, body: { unlock: true } })}>
                            Desbloquear
                          </button>
                        )}
                        <button type="button" className="btn small secondary" disabled={patch.isPending} onClick={() => resetPassword(u)}>
                          Restablecer contraseña
                        </button>
                        <button type="button" className="btn small soft" onClick={() => setAssigning(u)}>Asignar rol</button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {creating && (
        <CreateUserModal
          areas={areas.data?.items ?? []}
          onClose={() => setCreating(false)}
          onCreated={(result) => {
            setCreating(false);
            setIssued(result);
          }}
        />
      )}
      {assigning && (
        <AssignRoleModal
          user={assigning}
          roles={roles}
          areas={areas.data?.items ?? []}
          onClose={() => setAssigning(null)}
          onAssigned={() => {
            setAssigning(null);
            notify('Rol asignado.');
          }}
        />
      )}
      {revoking && (
        <RevokeModal
          user={revoking.user}
          assignment={revoking.assignment}
          onClose={() => setRevoking(null)}
          onRevoked={() => {
            setRevoking(null);
            notify('Rol revocado.');
          }}
        />
      )}
      {issued && <TemporaryPasswordModal issued={issued} onClose={() => setIssued(null)} />}
    </>
  );
}

function CreateUserModal({ areas, onClose, onCreated }: { areas: Area[]; onClose: () => void; onCreated: (issued: IssuedPassword) => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ username: '', email: '', full_name: '', area_id: '' });
  const [errors, setErrors] = useState<Record<string, string>>({});

  const mutation = useMutation({
    mutationFn: () =>
      adminApi.createUser({
        username: form.username.trim(),
        email: form.email.trim(),
        full_name: form.full_name.trim(),
        area_id: form.area_id ? Number(form.area_id) : undefined,
      }),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ['admin-users'] });
      onCreated({ username: result.user.username, password: result.temporary_password });
    },
    onError: (err) => setErrors(toApiError(err).fields),
  });

  const apiError = mutation.isError ? toApiError(mutation.error) : null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: Record<string, string> = {};
    const username = form.username.trim();
    const email = form.email.trim();
    const fullName = form.full_name.trim();
    if (username.length < 3 || username.length > 64) found.username = 'Entre 3 y 64 caracteres.';
    if (!EMAIL_PATTERN.test(email) || email.length > 120) found.email = 'Ingresá un correo válido.';
    if (fullName.length < 3 || fullName.length > 120) found.full_name = 'Entre 3 y 120 caracteres.';
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    mutation.mutate();
  }

  const fieldError = (key: string) => errors[key] ?? '';

  return (
    <Modal
      title="Nuevo usuario"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn secondary" onClick={onClose}>Cancelar</button>
          <button type="submit" form="create-user-form" className="btn" disabled={mutation.isPending}>
            {mutation.isPending ? 'Creando…' : 'Crear usuario'}
          </button>
        </>
      }
    >
      <form id="create-user-form" className="stack" noValidate onSubmit={submit}>
        {apiError && <ErrorNotice error={mutation.error} />}
        <div className="field">
          <label htmlFor="cu-full">Nombre completo <span className="req">*</span></label>
          <input id="cu-full" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} aria-invalid={fieldError('full_name') ? 'true' : undefined} />
          <div className="form-error">{fieldError('full_name')}</div>
        </div>
        <div className="fields-2">
          <div className="field">
            <label htmlFor="cu-username">Usuario <span className="req">*</span></label>
            <input id="cu-username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} aria-invalid={fieldError('username') ? 'true' : undefined} />
            <div className="form-error">{fieldError('username')}</div>
          </div>
          <div className="field">
            <label htmlFor="cu-email">Correo <span className="req">*</span></label>
            <input id="cu-email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} aria-invalid={fieldError('email') ? 'true' : undefined} />
            <div className="form-error">{fieldError('email')}</div>
          </div>
        </div>
        <div className="field">
          <label htmlFor="cu-area">Área</label>
          <select id="cu-area" value={form.area_id} onChange={(e) => setForm({ ...form, area_id: e.target.value })}>
            <option value="">Sin área</option>
            {areas.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
          <div className="field-help">Se genera una contraseña temporal que se muestra una sola vez.</div>
        </div>
      </form>
    </Modal>
  );
}

function TemporaryPasswordModal({ issued, onClose }: { issued: IssuedPassword; onClose: () => void }) {
  return (
    <Modal title="Contraseña temporal" onClose={onClose} footer={<button type="button" className="btn" onClick={onClose}>Listo, ya la guardé</button>}>
      <div className="stack">
        <Notice tone="amber">Se muestra una sola vez. Entregála a {issued.username} por un canal seguro; deberá cambiarla en su primer ingreso.</Notice>
        <div className="field">
          <label htmlFor="temp-password">Contraseña temporal</label>
          <input id="temp-password" readOnly value={issued.password} onFocus={(e) => e.currentTarget.select()} />
        </div>
      </div>
    </Modal>
  );
}

function AssignRoleModal({
  user,
  roles,
  areas,
  onClose,
  onAssigned,
}: {
  user: AdminUser;
  roles: AdminRole[];
  areas: Area[];
  onClose: () => void;
  onAssigned: () => void;
}) {
  const queryClient = useQueryClient();
  const [role, setRole] = useState('');
  const [areaId, setAreaId] = useState('');
  const [legalBasis, setLegalBasis] = useState('');
  const [validTo, setValidTo] = useState('');
  const [maxAmount, setMaxAmount] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});

  const mutation = useMutation({
    mutationFn: () =>
      adminApi.addAssignment(user.id, {
        role,
        area_id: areaId ? Number(areaId) : undefined,
        legal_basis: legalBasis.trim() || undefined,
        valid_to: validTo || undefined,
        max_amount: maxAmount.trim() ? normalizeDecimal(maxAmount) : undefined,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['admin-users'] });
      onAssigned();
    },
    onError: (err) => setErrors(toApiError(err).fields),
  });

  const apiError = mutation.isError ? toApiError(mutation.error) : null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: Record<string, string> = {};
    if (!role) found.role = 'Elegí un rol.';
    if (role === 'solicitante' && !areaId) found.area_id = 'El rol Solicitante requiere un área.';
    if (role === 'ordenador' && legalBasis.trim().length < 5) found.legal_basis = 'Indicá la resolución o delegación que respalda la competencia (mínimo 5 caracteres).';
    if (maxAmount.trim() && !DECIMAL_PATTERN.test(normalizeDecimal(maxAmount))) found.max_amount = 'Ingresá un monto válido, por ejemplo 150000.00.';
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    mutation.mutate();
  }

  const fieldError = (key: string) => errors[key] ?? '';

  return (
    <Modal
      title={`Asignar rol a ${user.full_name}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn secondary" onClick={onClose}>Cancelar</button>
          <button type="submit" form="assign-role-form" className="btn" disabled={mutation.isPending}>
            {mutation.isPending ? 'Asignando…' : 'Asignar'}
          </button>
        </>
      }
    >
      <form id="assign-role-form" className="stack" noValidate onSubmit={submit}>
        <Notice tone="blue">La competencia de un rol vale solo mientras esté vigente y no revocada. Cada cambio queda en la auditoría.</Notice>
        {apiError && <ErrorNotice error={mutation.error} />}
        <div className="fields-2">
          <div className="field">
            <label htmlFor="ar-role">Rol <span className="req">*</span></label>
            <select id="ar-role" value={role} onChange={(e) => setRole(e.target.value)} aria-invalid={fieldError('role') ? 'true' : undefined}>
              <option value="">Elegí un rol</option>
              {roles.map((r) => (
                <option key={r.code} value={r.code}>{r.name}</option>
              ))}
            </select>
            <div className="form-error">{fieldError('role')}</div>
          </div>
          <div className="field">
            <label htmlFor="ar-area">Área{role === 'solicitante' ? ' *' : ''}</label>
            <select id="ar-area" value={areaId} onChange={(e) => setAreaId(e.target.value)} aria-invalid={fieldError('area_id') ? 'true' : undefined}>
              <option value="">Sin área</option>
              {areas.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
            <div className="form-error">{fieldError('area_id')}</div>
          </div>
        </div>
        <div className="field">
          <label htmlFor="ar-basis">Resolución o delegación{role === 'ordenador' ? ' *' : ''}</label>
          <input id="ar-basis" value={legalBasis} onChange={(e) => setLegalBasis(e.target.value)} aria-invalid={fieldError('legal_basis') ? 'true' : undefined} />
          <div className="field-help">Obligatoria para el rol Ordenador. Respalda la competencia.</div>
          <div className="form-error">{fieldError('legal_basis')}</div>
        </div>
        <div className="fields-2">
          <div className="field">
            <label htmlFor="ar-valid-to">Vigente hasta</label>
            <input id="ar-valid-to" type="datetime-local" value={validTo} onChange={(e) => setValidTo(e.target.value)} />
            <div className="field-help">Sin fecha, la asignación queda vigente hasta que se revoque.</div>
          </div>
          <div className="field">
            <label htmlFor="ar-max">Tope de competencia (UYU)</label>
            <input id="ar-max" inputMode="decimal" value={maxAmount} onChange={(e) => setMaxAmount(e.target.value)} aria-invalid={fieldError('max_amount') ? 'true' : undefined} />
            <div className="form-error">{fieldError('max_amount')}</div>
          </div>
        </div>
      </form>
    </Modal>
  );
}

function RevokeModal({ user, assignment, onClose, onRevoked }: { user: AdminUser; assignment: AdminAssignment; onClose: () => void; onRevoked: () => void }) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');

  const mutation = useMutation({
    mutationFn: () => adminApi.revokeAssignment(assignment.id, reason.trim()),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['admin-users'] });
      onRevoked();
    },
    onError: (err) => setError(toApiError(err).message),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (reason.trim().length < 10) {
      setError('Indicá el motivo de la revocación (mínimo 10 caracteres).');
      return;
    }
    setError('');
    mutation.mutate();
  }

  return (
    <Modal
      title={`Revocar ${assignment.role_name ?? assignment.role}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn secondary" onClick={onClose}>Cancelar</button>
          <button type="submit" form="revoke-form" className="btn danger" disabled={mutation.isPending}>
            {mutation.isPending ? 'Revocando…' : 'Revocar rol'}
          </button>
        </>
      }
    >
      <form id="revoke-form" className="stack" noValidate onSubmit={submit}>
        <p className="muted">Se quita a {user.full_name} la competencia de este rol. La acción queda registrada en la auditoría.</p>
        {error && <Notice tone="red" role="alert">{error}</Notice>}
        <div className="field">
          <label htmlFor="rv-reason">Motivo <span className="req">*</span></label>
          <textarea id="rv-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
        </div>
      </form>
    </Modal>
  );
}

function AreasTab() {
  const queryClient = useQueryClient();
  const notify = useToast();
  const areas = useAreas();
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});

  const mutation = useMutation({
    mutationFn: () => adminApi.createArea({ code: code.trim(), name: name.trim() }),
    onSuccess: async (area) => {
      await queryClient.invalidateQueries({ queryKey: ['areas'] });
      notify(`Área ${area.code} creada.`);
      setCode('');
      setName('');
      setErrors({});
    },
    onError: (err) => {
      const apiError = toApiError(err);
      setErrors(apiError.fields);
      notify(apiError.message, 'error');
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: Record<string, string> = {};
    if (code.trim().length < 2 || code.trim().length > 30) found.code = 'Entre 2 y 30 caracteres.';
    if (name.trim().length < 3 || name.trim().length > 120) found.name = 'Entre 3 y 120 caracteres.';
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    mutation.mutate();
  }

  return (
    <div className="two-col">
      <section className="card">
        <div className="card-head"><h2>Áreas</h2></div>
        {areas.isPending && <Loading />}
        {areas.isError && <ErrorNotice error={areas.error} />}
        {areas.data && areas.data.items.length === 0 && <Empty title="No hay áreas cargadas." />}
        {areas.data && areas.data.items.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Código</th><th>Nombre</th></tr>
              </thead>
              <tbody>
                {areas.data.items.map((a) => (
                  <tr key={a.id}>
                    <td className="table-id">{a.code}</td>
                    <td>{a.name}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <div className="card-head"><h2>Nueva área</h2></div>
        <form className="stack" noValidate onSubmit={submit}>
          {mutation.isError && !Object.keys(errors).length && <ErrorNotice error={mutation.error} />}
          <div className="field">
            <label htmlFor="area-code">Código <span className="req">*</span></label>
            <input id="area-code" value={code} onChange={(e) => setCode(e.target.value)} aria-invalid={errors.code ? 'true' : undefined} />
            <div className="field-help">Se guarda en mayúsculas.</div>
            <div className="form-error">{errors.code ?? ''}</div>
          </div>
          <div className="field">
            <label htmlFor="area-name">Nombre <span className="req">*</span></label>
            <input id="area-name" value={name} onChange={(e) => setName(e.target.value)} aria-invalid={errors.name ? 'true' : undefined} />
            <div className="form-error">{errors.name ?? ''}</div>
          </div>
          <div>
            <button type="submit" className="btn" disabled={mutation.isPending}>{mutation.isPending ? 'Guardando…' : 'Crear área'}</button>
          </div>
        </form>
      </section>
    </div>
  );
}

function SegregationTab() {
  const query = useQuery({ queryKey: ['admin-segregation'], queryFn: () => adminApi.segregation() });
  const [target, setTarget] = useState<SegregationRule | null>(null);

  return (
    <>
      <Notice tone="blue">Las reglas de segregación impiden que una misma persona realice dos acciones incompatibles en un mismo expediente. Cada cambio exige un motivo y queda en la auditoría.</Notice>
      <div style={{ marginTop: 14 }}>
        {query.isPending && <Loading />}
        {query.isError && <ErrorNotice error={query.error} />}
        {query.data && query.data.items.length === 0 && <Empty title="No hay reglas de segregación cargadas." />}
        {query.data && query.data.items.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Acción A</th>
                  <th>Acción B</th>
                  <th>Estado</th>
                  <th>Motivo registrado</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((r) => (
                  <tr key={r.id}>
                    <td className="table-id">{r.action_a}</td>
                    <td className="table-id">{r.action_b}</td>
                    <td>
                      <div className="row">
                        <button
                          type="button"
                          role="switch"
                          className="toggle"
                          aria-checked={r.active}
                          aria-label={`Regla ${r.action_a} con ${r.action_b}`}
                          onClick={() => setTarget(r)}
                        />
                        <span className="small-text">{r.active ? 'Activa' : 'Inactiva'}</span>
                      </div>
                    </td>
                    <td className="small-text">{r.reason ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {target && <SegregationModal rule={target} onClose={() => setTarget(null)} />}
    </>
  );
}

function SegregationModal({ rule, onClose }: { rule: SegregationRule; onClose: () => void }) {
  const queryClient = useQueryClient();
  const notify = useToast();
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const nextActive = !rule.active;

  const mutation = useMutation({
    mutationFn: () => adminApi.patchSegregation(rule.id, { active: nextActive, reason: reason.trim() }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['admin-segregation'] });
      notify(nextActive ? 'Regla activada.' : 'Regla desactivada.');
      onClose();
    },
    onError: (err) => setError(toApiError(err).message),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (reason.trim().length < 10) {
      setError('Indicá el motivo del cambio (mínimo 10 caracteres).');
      return;
    }
    setError('');
    mutation.mutate();
  }

  return (
    <Modal
      title={nextActive ? 'Activar regla de segregación' : 'Desactivar regla de segregación'}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn secondary" onClick={onClose}>Cancelar</button>
          <button type="submit" form="segregation-form" className="btn" disabled={mutation.isPending}>
            {mutation.isPending ? 'Guardando…' : 'Confirmar cambio'}
          </button>
        </>
      }
    >
      <form id="segregation-form" className="stack" noValidate onSubmit={submit}>
        {!nextActive && <Notice tone="amber">Desactivar la regla permite que una misma persona realice ambas acciones en un expediente.</Notice>}
        <p className="muted small-text"><span className="table-id">{rule.action_a}</span> con <span className="table-id">{rule.action_b}</span></p>
        {error && <Notice tone="red" role="alert">{error}</Notice>}
        <div className="field">
          <label htmlFor="seg-reason">Motivo <span className="req">*</span></label>
          <textarea id="seg-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
        </div>
      </form>
    </Modal>
  );
}

function HolidaysTab() {
  const notify = useToast();
  const [day, setDay] = useState('');
  const [name, setName] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});

  const mutation = useMutation({
    mutationFn: () => adminApi.createHoliday(day, name.trim()),
    onSuccess: () => {
      notify('Feriado registrado.');
      setDay('');
      setName('');
      setErrors({});
    },
    onError: (err) => notify(toApiError(err).message, 'error'),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: Record<string, string> = {};
    if (!day) found.day = 'Elegí la fecha.';
    if (name.trim().length < 3 || name.trim().length > 120) found.name = 'Entre 3 y 120 caracteres.';
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    mutation.mutate();
  }

  return (
    <div className="two-col">
      <section className="card">
        <div className="card-head"><h2>Feriados</h2></div>
        <Notice tone="blue">Esta pantalla solo registra feriados nuevos. La lista vigente no se muestra aquí todavía; si un feriado ya existe, el registro no lo duplica.</Notice>
      </section>
      <section className="card">
        <div className="card-head"><h2>Nuevo feriado</h2></div>
        <form className="stack" noValidate onSubmit={submit}>
          <div className="field">
            <label htmlFor="hol-day">Fecha <span className="req">*</span></label>
            <input id="hol-day" type="date" value={day} onChange={(e) => setDay(e.target.value)} aria-invalid={errors.day ? 'true' : undefined} />
            <div className="form-error">{errors.day ?? ''}</div>
          </div>
          <div className="field">
            <label htmlFor="hol-name">Nombre <span className="req">*</span></label>
            <input id="hol-name" value={name} onChange={(e) => setName(e.target.value)} aria-invalid={errors.name ? 'true' : undefined} />
            <div className="form-error">{errors.name ?? ''}</div>
          </div>
          <div>
            <button type="submit" className="btn" disabled={mutation.isPending}>{mutation.isPending ? 'Guardando…' : 'Registrar feriado'}</button>
          </div>
        </form>
      </section>
    </div>
  );
}
