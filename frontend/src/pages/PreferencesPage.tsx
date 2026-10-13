import { ChangePasswordForm } from '../components/ChangePasswordForm';
import { usePreferences } from '../store/preferences';

const OPTIONS = [
  { key: 'bigText', label: 'Texto ampliado', help: 'Aumenta el tamaño del texto en toda la aplicación.' },
  { key: 'highContrast', label: 'Alto contraste', help: 'Refuerza los colores de texto y bordes.' },
  { key: 'reduceMotion', label: 'Reducir animaciones', help: 'Elimina transiciones y movimientos no esenciales.' },
] as const;

export function PreferencesPage() {
  const prefs = usePreferences();

  return (
    <>
      <header className="page-heading">
        <div>
          <div className="eyebrow">Cuenta</div>
          <h1>Preferencias</h1>
          <p className="muted">Estas preferencias de accesibilidad se guardan solo en este navegador. No contienen datos de expedientes ni de permisos.</p>
        </div>
      </header>

      <div className="two-col">
        <section className="card">
          <div className="card-head"><h2>Accesibilidad</h2></div>
          {OPTIONS.map((option) => {
            const checked = prefs[option.key];
            return (
              <div key={option.key} className="toggle-row">
                <div>
                  <div id={`pref-${option.key}-label`} className="table-title">{option.label}</div>
                  <div className="small-text muted">{option.help}</div>
                </div>
                <button
                  type="button"
                  role="switch"
                  className="toggle"
                  aria-checked={checked}
                  aria-labelledby={`pref-${option.key}-label`}
                  onClick={() => prefs.setPref(option.key, !checked)}
                />
              </div>
            );
          })}
        </section>

        <section className="card">
          <div className="card-head"><h2>Cambiar contraseña</h2></div>
          <ChangePasswordForm />
        </section>
      </div>
    </>
  );
}
