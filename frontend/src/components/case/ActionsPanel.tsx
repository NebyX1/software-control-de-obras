import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { casesApi } from '../../api/endpoints';
import { isConflict, toApiError } from '../../api/client';
import type { ActionInfo, CaseDocument } from '../../api/types';
import { Badge, ErrorNotice, Modal, Notice, useToast } from '../ui';
import { DynamicForm, buildPayload, initialValues, validateValues, type FormErrors, type FormValues } from '../DynamicForm';
import { joinResponsible, uuid } from '../../lib/format';
import { invalidateCase } from './caseQueries';

interface ActionsPanelProps {
  code: string;
  version: number;
  actions: ActionInfo[];
  documents: CaseDocument[];
}

export function ActionsPanel({ code, version, actions, documents }: ActionsPanelProps) {
  const [open, setOpen] = useState<ActionInfo | null>(null);

  if (actions.length === 0) {
    return <p className="muted">No hay acciones disponibles para tu rol en esta etapa.</p>;
  }

  return (
    <>
      <div className="offer-cards" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))' }}>
        {actions.map((a) => {
          const enabled = a.can && a.blockers.length === 0 && !a.done;
          return (
            <article key={a.name} className="card" aria-label={a.label}>
              <div className="card-head">
                <h3 style={{ margin: 0, fontSize: 15 }}>{a.label}</h3>
                {a.done ? <Badge tone="green">Hecho</Badge> : a.blockers.length > 0 ? <Badge tone="amber">Bloqueada</Badge> : null}
              </div>
              <p className="small-text muted">{a.description}</p>
              <p className="small-text"><strong>Responsable:</strong> {joinResponsible(a.responsible)}</p>
              {a.blockers.length > 0 && (
                <ul className="helper-list small-text">
                  {a.blockers.map((b) => <li key={b}>{b}</li>)}
                </ul>
              )}
              <button
                type="button"
                className={`btn small${a.danger ? ' danger' : ''}`}
                disabled={!enabled}
                onClick={() => setOpen(a)}
              >
                {a.done ? 'Completada' : a.label}
              </button>
            </article>
          );
        })}
      </div>
      {open && (
        <ActionModal
          key={open.name}
          code={code}
          version={version}
          action={open}
          documents={documents}
          onClose={() => setOpen(null)}
        />
      )}
    </>
  );
}

interface ActionModalProps {
  code: string;
  version: number;
  action: ActionInfo;
  documents: CaseDocument[];
  onClose: () => void;
}

function ActionModal({ code, version, action, documents, onClose }: ActionModalProps) {
  const queryClient = useQueryClient();
  const notify = useToast();
  const [idempotencyKey] = useState(() => uuid());
  const [values, setValues] = useState<FormValues>(() => initialValues(action.form));
  const [errors, setErrors] = useState<FormErrors>({});
  const [formError, setFormError] = useState<unknown>(null);

  const mutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => casesApi.action(code, action.name, body),
    onSuccess: async () => {
      await invalidateCase(queryClient, code);
      notify(`${action.label}: registrado.`);
      onClose();
    },
    onError: async (err) => {
      if (isConflict(err)) {
        notify('La compra cambió mientras trabajabas en ella. Actualizamos el expediente; revisalo antes de volver a intentar.', 'error');
        await invalidateCase(queryClient, code);
        onClose();
        return;
      }
      const apiErr = toApiError(err);
      if (apiErr.fields && Object.keys(apiErr.fields).length > 0) {
        setErrors(apiErr.fields);
      } else {
        setFormError(err);
      }
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = validateValues(action.form, values);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    setFormError(null);
    mutation.mutate({
      ...buildPayload(action.form, values),
      expected_version: version,
      idempotency_key: idempotencyKey,
    });
  }

  return (
    <Modal
      title={action.label}
      onClose={() => {
        if (!mutation.isPending) onClose();
      }}
      footer={
        <>
          <button type="button" className="btn secondary" onClick={onClose} disabled={mutation.isPending}>Cancelar</button>
          <button type="submit" form={`action-form-${action.name}`} className={`btn${action.danger ? ' danger' : ''}`} disabled={mutation.isPending}>
            {mutation.isPending ? 'Registrando…' : action.label}
          </button>
        </>
      }
    >
      <p className="muted">{action.description}</p>
      {formError != null && <ErrorNotice error={formError} />}
      {action.form.length === 0 && <Notice tone="blue">Esta acción se registra en la auditoría con tu usuario y rol.</Notice>}
      <DynamicForm
        id={`action-form-${action.name}`}
        fields={action.form}
        values={values}
        onChange={setValues}
        errors={errors}
        documents={documents}
        onSubmit={submit}
      />
    </Modal>
  );
}
