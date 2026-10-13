import { Navigate, Route, Routes } from 'react-router-dom';
import { Loading, ToastProvider, Notice } from './components/ui';
import { ChangePasswordForm } from './components/ChangePasswordForm';
import { Layout, RequirePermission } from './components/Layout';
import { SessionProvider, useSession, useSessionQuery } from './session';
import { LoginPage } from './pages/LoginPage';
import { DashboardPage } from './pages/DashboardPage';
import { CasesPage } from './pages/CasesPage';
import { CaseDetailPage } from './pages/CaseDetailPage';
import { EvaluatePage } from './pages/EvaluatePage';
import { RulesPage } from './pages/RulesPage';
import { AuditPage } from './pages/AuditPage';
import { AdminPage } from './pages/AdminPage';
import { PreferencesPage } from './pages/PreferencesPage';

export function App() {
  return (
    <ToastProvider>
      <AppRoutes />
    </ToastProvider>
  );
}

function AppRoutes() {
  const session = useSessionQuery();

  if (session.isPending) {
    return (
      <div className="login-wrap">
        <Loading label="Verificando sesión…" />
      </div>
    );
  }

  if (session.isError || !session.data) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <SessionProvider user={session.data}>
      {session.data.must_change_password ? <ForcedPasswordChange /> : <AuthenticatedRoutes />}
    </SessionProvider>
  );
}

function AuthenticatedRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<RequirePermission permission="dashboard.read"><DashboardPage /></RequirePermission>} />
        <Route path="compras" element={<RequirePermission permission="case.read"><CasesPage /></RequirePermission>} />
        <Route path="compras/:code" element={<RequirePermission permission="case.read"><CaseDetailPage /></RequirePermission>} />
        <Route path="evaluar" element={<RequirePermission permission="evaluation.read"><EvaluatePage /></RequirePermission>} />
        <Route path="reglas" element={<RulesPage />} />
        <Route path="auditoria" element={<RequirePermission permission="audit.read"><AuditPage /></RequirePermission>} />
        <Route path="administracion" element={<RequirePermission anyOf={['admin.users', 'admin.areas', 'admin.rules']}><AdminPage /></RequirePermission>} />
        <Route path="preferencias" element={<PreferencesPage />} />
        <Route path="login" element={<Navigate to="/" replace />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

function NotFound() {
  return (
    <div className="empty">
      <strong>No encontramos esta página.</strong>
      <div><a href="/">Volver al escritorio</a></div>
    </div>
  );
}

function ForcedPasswordChange() {
  const { logout } = useSession();
  return (
    <div className="login-wrap">
      <div className="card login-card">
        <h1 style={{ fontSize: 24, marginTop: 0 }}>Cambiá tu contraseña</h1>
        <Notice tone="amber">Es tu primer ingreso o un administrador restableció tu contraseña. Para continuar, elegí una nueva.</Notice>
        <div style={{ marginTop: 18 }}>
          <ChangePasswordForm />
        </div>
        <button type="button" className="text-btn" style={{ marginTop: 12 }} onClick={() => void logout()}>
          Cerrar sesión
        </button>
      </div>
    </div>
  );
}
