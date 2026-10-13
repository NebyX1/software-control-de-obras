import { useId, type FormEvent, type ReactNode } from 'react';
import type { CaseDocument, FormField } from '../api/types';
import { DOCUMENT_KINDS } from '../lib/labels';

export type FormValues = Record<string, unknown>;
export type FormErrors = Record<string, string>;

export function initialValues(fields: FormField[]): FormValues {
  const out: FormValues = {};
  for (const f of fields) {
    if (f.type === 'lines') {
      out[f.name] = Array.isArray(f.default) ? (f.default as FormValues[]).map((row) => ({ ...row })) : [];
    } else if (f.type === 'checkbox') {
      out[f.name] = Boolean(f.default);
    } else {
      out[f.name] = f.default ?? '';
    }
  }
  return out;
}

function isEmpty(value: unknown) {
  return value === undefined || value === null || (typeof value === 'string' && value.trim() === '');
}

export function validateValues(fields: FormField[], values: FormValues, prefix = ''): FormErrors {
  const errors: FormErrors = {};
  for (const f of fields) {
    const key = prefix ? `${prefix}.${f.name}` : f.name;
    const value = values[f.name];

    if (f.type === 'lines') {
      const rows = Array.isArray(value) ? (value as FormValues[]) : [];
      if (rows.length === 0 && f.required) errors[key] = 'Agregá al menos un renglón.';
      rows.forEach((row, i) => Object.assign(errors, validateValues(f.fields ?? [], row, `${key}.${i}`)));
      continue;
    }

    if (f.type === 'checkbox') {
      if (f.required && value !== true) errors[key] = 'Este paso requiere marcar la casilla.';
      continue;
    }

    if (isEmpty(value)) {
      if (f.required) errors[key] = 'Campo obligatorio.';
      continue;
    }

    if (f.type === 'number' || f.type === 'money') {
      const n = Number(String(value).replace(',', '.'));
      if (Number.isNaN(n)) errors[key] = 'Ingresá un número válido.';
      else if (f.min !== undefined && n < f.min) errors[key] = `Debe ser al menos ${f.min}.`;
      else if (f.max !== undefined && n > f.max) errors[key] = `No puede superar ${f.max}.`;
    }
  }
  return errors;
}

export function buildPayload(fields: FormField[], values: FormValues): FormValues {
  const out: FormValues = {};
  for (const f of fields) {
    const value = values[f.name];

    if (f.type === 'lines') {
      const rows = Array.isArray(value) ? (value as FormValues[]) : [];
      out[f.name] = rows.map((row) => buildPayload(f.fields ?? [], row));
      continue;
    }

    if (f.type === 'checkbox') {
      out[f.name] = Boolean(value);
      continue;
    }

    if (isEmpty(value)) continue;

    if (f.type === 'document') {
      out[f.name] = Number(value);
      continue;
    }

    if (f.type === 'select') {
      // El backend compara con el valor original de la opción (puede ser numérico).
      const option = f.options?.find((o) => String(o.value) === String(value));
      out[f.name] = option ? option.value : value;
      continue;
    }

    out[f.name] = typeof value === 'string' ? value.trim() : value;
  }
  return out;
}

interface FormProps {
  id: string;
  fields: FormField[];
  values: FormValues;
  onChange: (values: FormValues) => void;
  errors: FormErrors;
  documents?: CaseDocument[];
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}

export function DynamicForm({ id, fields, values, onChange, errors, documents, onSubmit }: FormProps) {
  return (
    <form id={id} className="stack" noValidate onSubmit={onSubmit}>
      <FieldList fields={fields} values={values} onChange={onChange} errors={errors} path="" documents={documents} />
    </form>
  );
}

interface ListProps {
  fields: FormField[];
  values: FormValues;
  onChange: (values: FormValues) => void;
  errors: FormErrors;
  path: string;
  documents?: CaseDocument[];
}

function FieldList({ fields, values, onChange, errors, path, documents }: ListProps) {
  return (
    <>
      {fields.map((f) => {
        const childPath = path ? `${path}.${f.name}` : f.name;
        return (
          <FieldControl
            key={f.name}
            field={f}
            value={values[f.name]}
            path={childPath}
            errors={errors}
            documents={documents}
            onChange={(v) => onChange({ ...values, [f.name]: v })}
          />
        );
      })}
    </>
  );
}

interface ControlProps {
  field: FormField;
  value: unknown;
  path: string;
  errors: FormErrors;
  documents?: CaseDocument[];
  onChange: (value: unknown) => void;
}

function FieldControl({ field: f, value, path, errors, documents, onChange }: ControlProps) {
  const reactId = useId();
  const controlId = `${reactId}-control`;
  const helpId = `${reactId}-help`;
  const errorId = `${reactId}-error`;
  const error = errors[path];
  const described = [f.help ? helpId : '', error ? errorId : ''].filter(Boolean).join(' ') || undefined;
  const label = (
    <>
      {f.label}
      {f.required && <span className="req" aria-hidden="true"> *</span>}
    </>
  );

  if (f.type === 'lines') {
    return (
      <LinesEditor field={f} rows={Array.isArray(value) ? (value as FormValues[]) : []} path={path} errors={errors} documents={documents} onChange={onChange} />
    );
  }

  if (f.type === 'checkbox') {
    return (
      <div className="field">
        <label className="check">
          <input
            type="checkbox"
            id={controlId}
            checked={value === true}
            aria-describedby={described}
            onChange={(e) => onChange(e.target.checked)}
          />
          <span>{label}</span>
        </label>
        {f.help && <div className="field-help" id={helpId}>{f.help}</div>}
        {error && <div className="form-error show" id={errorId} role="alert">{error}</div>}
      </div>
    );
  }

  const str = value === undefined || value === null ? '' : String(value);
  let control: ReactNode;

  if (f.type === 'textarea') {
    control = (
      <textarea id={controlId} rows={f.rows ?? 3} value={str} aria-required={f.required || undefined} aria-invalid={!!error || undefined} aria-describedby={described} onChange={(e) => onChange(e.target.value)} />
    );
  } else if (f.type === 'select' || f.type === 'document') {
    const options = f.options ?? (f.type === 'document'
      ? (documents ?? []).map((d) => ({ value: String(d.id), label: `${d.title} (${DOCUMENT_KINDS[d.kind] ?? d.kind})` }))
      : []);
    control = (
      <select id={controlId} value={str} aria-required={f.required || undefined} aria-invalid={!!error || undefined} aria-describedby={described} onChange={(e) => onChange(e.target.value)}>
        <option value="">{f.placeholder ?? (f.type === 'document' ? 'Sin documento' : 'Elegí una opción')}</option>
        {options.map((o) => (
          <option key={String(o.value)} value={String(o.value)}>{o.label}</option>
        ))}
      </select>
    );
  } else {
    const inputType = f.type === 'number' || f.type === 'money' ? 'number' : f.type === 'date' ? 'date' : f.type === 'datetime' ? 'datetime-local' : 'text';
    control = (
      <input
        id={controlId}
        type={inputType}
        step={inputType === 'number' ? 'any' : undefined}
        inputMode={f.type === 'money' ? 'decimal' : undefined}
        value={str}
        placeholder={f.placeholder}
        aria-required={f.required || undefined}
        aria-invalid={!!error || undefined}
        aria-describedby={described}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  return (
    <div className="field">
      <label htmlFor={controlId}>{label}</label>
      {control}
      {f.help && <div className="field-help" id={helpId}>{f.help}</div>}
      {error && <div className="form-error show" id={errorId} role="alert">{error}</div>}
    </div>
  );
}

interface LinesProps {
  field: FormField;
  rows: FormValues[];
  path: string;
  errors: FormErrors;
  documents?: CaseDocument[];
  onChange: (value: unknown) => void;
}

function LinesEditor({ field, rows, path, errors, documents, onChange }: LinesProps) {
  const error = errors[path];
  return (
    <fieldset className="field">
      <legend>
        {field.label}
        {field.required && <span className="req" aria-hidden="true"> *</span>}
      </legend>
      {field.help && <div className="field-help">{field.help}</div>}
      {rows.length === 0 && <div className="field-help">Todavía no hay renglones.</div>}
      {rows.map((row, i) => (
        <div className="line-row" key={i}>
          <div className="line-row-head">
            <strong>Renglón {i + 1}</strong>
            <button type="button" className="text-btn" onClick={() => onChange(rows.filter((_, j) => j !== i))}>
              Quitar
            </button>
          </div>
          <FieldList
            fields={field.fields ?? []}
            values={row}
            path={`${path}.${i}`}
            errors={errors}
            documents={documents}
            onChange={(next) => onChange(rows.map((r, j) => (j === i ? next : r)))}
          />
        </div>
      ))}
      <button type="button" className="btn secondary small" onClick={() => onChange([...rows, initialValues(field.fields ?? [])])}>
        Agregar renglón
      </button>
      {error && <div className="form-error show" role="alert">{error}</div>}
    </fieldset>
  );
}
