import { useEffect, useState, type ReactNode } from 'react';
import { Link, Navigate, NavLink, Outlet, useLocation } from 'react-router-dom';
import { useSession } from '../session';
import { usePreferences } from '../store/preferences';
import { ROLE_LABELS } from '../lib/labels';

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
  visible: boolean;
}

const ROUTE_TITLES: [string, string][] = [
  ['/compras', 'Solicitudes y compras'],
  ['/evaluar', 'Comparar ofertas'],
  ['/reglas', 'Normativa y flujo'],
  ['/auditoria', 'Auditoría'],
  ['/administracion', 'Administración'],
  ['/preferencias', 'Preferencias'],
];

function crumbFor(pathname: string): string {
  if (pathname === '/') return 'Mi escritorio';
  const match = ROUTE_TITLES.find(([prefix]) => pathname === prefix || pathname.startsWith(`${prefix}/`));
  return match ? match[1] : 'Compra Clara';
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return 'CC';
  return parts.slice(0, 2).map((p) => p[0]!.toUpperCase()).join('');
}

export function Layout() {
  const { user, can, logout } = useSession();
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const bigText = usePreferences((s) => s.bigText);
  const highContrast = usePreferences((s) => s.highContrast);
  const reduceMotion = usePreferences((s) => s.reduceMotion);

  useEffect(() => {
    document.body.classList.toggle('big-text', bigText);
    document.body.classList.toggle('high-contrast', highContrast);
    document.body.classList.toggle('no-motion', reduceMotion);
  }, [bigText, highContrast, reduceMotion]);

  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  const items: NavItem[] = [
    { to: '/', label: 'Mi escritorio', end: true, visible: can('case.read') },
    { to: '/compras', label: 'Solicitudes y compras', visible: can('case.read') },
    { to: '/evaluar', label: 'Comparar ofertas', visible: can('offer.read') },
  ];
  const control: NavItem[] = [
    { to: '/auditoria', label: 'Auditoría', visible: can('audit.read') },
    { to: '/reglas', label: 'Normativa y flujo', visible: true },
    { to: '/administracion', label: 'Administración', visible: can('admin.users') || can('admin.areas') || can('admin.rules') },
    { to: '/preferencias', label: 'Preferencias', visible: true },
  ];

  const renderNav = (list: NavItem[]) =>
    list
      .filter((item) => item.visible)
      .map((item) => (
        <NavLink key={item.to} to={item.to} end={item.end}>
          {item.label}
        </NavLink>
      ));

  return (
    <>
      <a className="skip" href="#main">Saltar al contenido</a>
      <aside className={`sidebar ${drawerOpen ? 'open' : ''}`} id="sidebar" aria-label="Navegación principal">
        <Link to="/" className="brand">
          <span className="brand-mark" aria-hidden="true">✓</span>
          <span>
            <strong>compra clara<span style={{ color: 'var(--primary)' }}>.</span></strong>
            <span>Lavalleja</span>
          </span>
        </Link>
        <nav>
          <div className="nav-group-label">Tu día a día</div>
          <div className="nav">{renderNav(items)}</div>
          <div className="nav-group-label" style={{ marginTop: 18 }}>Control y consulta</div>
          <div className="nav">{renderNav(control)}</div>
        </nav>
        <div className="sidebar-foot">
          Sesión de {ROLE_LABELS[user.roles[0] ?? ''] ?? 'usuario'} · {user.area ?? 'Sin área asignada'}
        </div>
      </aside>
      <div className={`drawer-backdrop ${drawerOpen ? 'open' : ''}`} onClick={() => setDrawerOpen(false)} aria-hidden="true" />
      <div className="workspace">
        <header className="topbar">
          <div className="row">
            <button
              type="button"
              className="btn secondary menu-btn"
              aria-label="Abrir navegación"
              aria-expanded={drawerOpen}
              aria-controls="sidebar"
              onClick={() => setDrawerOpen((v) => !v)}
            >
              ☰
            </button>
            <div className="crumb">Compras públicas › <strong>{crumbFor(location.pathname)}</strong></div>
          </div>
          <div className="user-chip">
            <span className="avatar" aria-hidden="true">{initials(user.full_name)}</span>
            <span className="name">{user.full_name}</span>
            <button type="button" className="btn secondary small" onClick={() => void logout()}>
              Cerrar sesión
            </button>
          </div>
        </header>
        <main id="main" className="content" tabIndex={-1}>
          <Outlet />
        </main>
        <footer className="footer">
          <span>Compra Clara · Sistema de compras públicas para Lavalleja</span>
        </footer>
      </div>
    </>
  );
}

export function RequirePermission({ permission, anyOf, children }: { permission?: string; anyOf?: string[]; children: ReactNode }) {
  const { can } = useSession();
  const allowed = anyOf ? anyOf.some((p) => can(p)) : permission ? can(permission) : true;
  if (!allowed) {
    return (
      <div className="empty">
        <strong>Tu rol no tiene acceso a esta sección.</strong>
        <div>Si lo necesitás, pedilo a un administrador.</div>
      </div>
    );
  }
  return <>{children}</>;
}

export function ToLogin() {
  return <Navigate to="/login" replace />;
}
