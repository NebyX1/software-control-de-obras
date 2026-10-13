import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { authApi } from '../api/endpoints';
import { setCsrfToken } from '../api/client';
import { SESSION_KEY } from '../session';
import { ErrorNotice, Notice } from '../components/ui';

export function LoginPage() {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [captcha, setCaptcha] = useState('');
  const [step, setStep] = useState<'credentials' | 'code'>('credentials');
  const [code, setCode] = useState('');

  const challenge = useQuery({
    queryKey: ['auth-challenge'],
    queryFn: async () => {
      const data = await authApi.challenge();
      setCsrfToken(data.csrf_token);
      return data;
    },
    retry: false,
    staleTime: 0,
    gcTime: 0,
  });

  const login = useMutation({
    mutationFn: () => authApi.login(email.trim(), password, challenge.data?.captcha ? captcha.trim() : undefined),
    onSuccess: (res) => {
      if (res.requires_2fa) {
        setStep('code');
        setPassword('');
        return;
      }
      if (res.csrf_token) setCsrfToken(res.csrf_token);
      if (res.user) queryClient.setQueryData(SESSION_KEY, res.user);
    },
    onError: () => {
      setPassword('');
      setCaptcha('');
      void challenge.refetch();
    },
  });

  const verify = useMutation({
    mutationFn: () => authApi.verify2fa(code.trim()),
    onSuccess: (res) => {
      setCsrfToken(res.csrf_token);
      queryClient.setQueryData(SESSION_KEY, res.user);
    },
    onError: () => setCode(''),
  });

  const submitCredentials = (event: FormEvent) => {
    event.preventDefault();
    login.mutate();
  };

  const submitCode = (event: FormEvent) => {
    event.preventDefault();
    verify.mutate();
  };

  return (
    <div className="login-wrap">
      <div className="card login-card">
        <div className="row" style={{ marginBottom: 18 }}>
          <span className="brand-mark" aria-hidden="true">✓</span>
          <div>
            <strong>compra clara<span style={{ color: 'var(--primary)' }}>.</span></strong>
            <div className="field-help">Lavalleja · acceso al sistema</div>
          </div>
        </div>

        {challenge.isPending && <Notice>Preparando el ingreso…</Notice>}
        {challenge.isError && <ErrorNotice error={challenge.error} />}

        {step === 'credentials' && challenge.isSuccess && (
          <form className="stack" noValidate onSubmit={submitCredentials}>
            <h1 style={{ fontSize: 24, margin: 0 }}>Iniciar sesión</h1>
            {login.isError && <ErrorNotice error={login.error} />}
            <div className="field">
              <label htmlFor="login-email">Correo electrónico</label>
              <input id="login-email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="login-password">Contraseña</label>
              <input id="login-password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
            {challenge.data.captcha && (
              <div className="field">
                <label htmlFor="login-captcha">Verificación: {challenge.data.captcha.question}</label>
                <input id="login-captcha" type="text" autoComplete="off" required value={captcha} onChange={(e) => setCaptcha(e.target.value)} />
              </div>
            )}
            <button type="submit" className="btn" disabled={login.isPending}>
              {login.isPending ? 'Verificando…' : 'Ingresar'}
            </button>
          </form>
        )}

        {step === 'code' && (
          <form className="stack" noValidate onSubmit={submitCode}>
            <h1 style={{ fontSize: 24, margin: 0 }}>Código de verificación</h1>
            <p className="field-help">Te enviamos un código de 6 dígitos a tu correo. Vence en 10 minutos.</p>
            {verify.isError && <ErrorNotice error={verify.error} />}
            <div className="field">
              <label htmlFor="login-code">Código</label>
              <input id="login-code" className="code-input" type="text" inputMode="numeric" autoComplete="one-time-code" maxLength={6} required value={code} onChange={(e) => setCode(e.target.value)} />
            </div>
            <button type="submit" className="btn" disabled={verify.isPending}>
              {verify.isPending ? 'Verificando…' : 'Confirmar'}
            </button>
            <button type="button" className="text-btn" onClick={() => { setStep('credentials'); setCode(''); void challenge.refetch(); }}>
              Volver
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
