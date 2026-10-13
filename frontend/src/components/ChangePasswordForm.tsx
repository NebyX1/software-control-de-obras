import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { authApi } from '../api/endpoints';
import { toApiError } from '../api/client';
import { SESSION_KEY } from '../session';
import { ErrorNotice, Notice, useToast } from './ui';

export function ChangePasswordForm({ onDone }: { onDone?: () => void }) {
  const queryClient = useQueryClient();
  const notify = useToast();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [mismatch, setMismatch] = useState(false);

  const mutation = useMutation({
    mutationFn: () => authApi.changePassword(current, next),
    onSuccess: async () => {
      notify('Contraseña actualizada.');
      setCurrent('');
      setNext('');
      setConfirm('');
      await queryClient.invalidateQueries({ queryKey: SESSION_KEY });
      onDone?.();
    },
  });

  const apiError = mutation.isError ? toApiError(mutation.error) : null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (next !== confirm) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    mutation.mutate();
  }

  return (
    <form className="stack" onSubmit={submit} noValidate aria-label="Cambiar contraseña">
      {mutation.isError && <ErrorNotice error={mutation.error} />}
      <div className="field">
        <label htmlFor="cp-current">Contraseña actual <span className="req">*</span></label>
        <input
          id="cp-current"
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          aria-invalid={apiError?.fields?.current ? 'true' : undefined}
          required
        />
        <div className="form-error">{apiError?.fields?.current ?? ''}</div>
      </div>
      <div className="field">
        <label htmlFor="cp-new">Contraseña nueva <span className="req">*</span></label>
        <input
          id="cp-new"
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          aria-invalid={apiError?.fields?.new ? 'true' : undefined}
          required
        />
        <div className="field-help">Usá una contraseña distinta a las anteriores.</div>
        <div className="form-error">{apiError?.fields?.new ?? ''}</div>
      </div>
      <div className="field">
        <label htmlFor="cp-confirm">Repetí la contraseña nueva <span className="req">*</span></label>
        <input
          id="cp-confirm"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          aria-invalid={mismatch ? 'true' : undefined}
          required
        />
        <div className="form-error">{mismatch ? 'Las contraseñas no coinciden.' : ''}</div>
      </div>
      {mutation.isSuccess && <Notice tone="green">Contraseña actualizada.</Notice>}
      <div>
        <button type="submit" className="btn" disabled={mutation.isPending}>
          {mutation.isPending ? 'Guardando…' : 'Guardar contraseña'}
        </button>
      </div>
    </form>
  );
}
