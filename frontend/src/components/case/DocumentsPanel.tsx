import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { documentsApi } from '../../api/endpoints';
import { toApiError } from '../../api/client';
import type { CaseDocument, DocumentVersion } from '../../api/types';
import { Badge, Empty, ErrorNotice, Modal, useToast } from '../ui';
import { CLASSIFICATION_LABELS, DOCUMENT_KINDS } from '../../lib/labels';
import { formatBytes, formatDateTime } from '../../lib/format';
import { useSession } from '../../session';
import { invalidateCase } from './caseQueries';

function latestVersion(doc: CaseDocument): DocumentVersion | undefined {
  return doc.versions.reduce<DocumentVersion | undefined>((best, v) => (!best || v.version > best.version ? v : best), undefined);
}

export function DocumentsPanel({ code, documents }: { code: string; documents: CaseDocument[] }) {
  const { can } = useSession();
  const notify = useToast();
  const [uploading, setUploading] = useState(false);
  const [versioning, setVersioning] = useState<CaseDocument | null>(null);

  async function download(doc: CaseDocument) {
    const v = latestVersion(doc);
    if (!v) return;
    try {
      await documentsApi.download(doc.id, v.version, v.original_name);
    } catch (err) {
      notify(toApiError(err).message || 'No pudimos descargar el documento.', 'error');
    }
  }

  return (
    <>
      <div className="row" style={{ justifyContent: 'flex-end', marginBottom: 10 }}>
        {can('document.upload') && (
          <button type="button" className="btn soft small" onClick={() => setUploading(true)}>Cargar documento</button>
        )}
      </div>
      {documents.length === 0 ? (
        <Empty title="Todavía no hay documentos en este expediente." />
      ) : (
        <ul className="stack" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {documents.map((doc) => {
            const v = latestVersion(doc);
            return (
              <li key={doc.id} className="doc">
                <div className="grow">
                  <strong>{doc.title}</strong>
                  <div className="small-text muted">
                    {DOCUMENT_KINDS[doc.kind] ?? doc.kind} · {CLASSIFICATION_LABELS[doc.classification] ?? doc.classification}
                    {v ? ` · versión ${v.version} · ${formatBytes(v.size)} · ${formatDateTime(v.uploaded_at)}` : ''}
                  </div>
                  {doc.external_reference && <div className="small-text muted">Referencia externa: {doc.external_reference}</div>}
                </div>
                <div className="row">
                  {doc.sealed && <Badge tone="purple">Sellado</Badge>}
                  {v && doc.can_download && (
                    <button type="button" className="btn secondary small" onClick={() => void download(doc)}>Descargar</button>
                  )}
                  {can('document.upload') && (
                    <button type="button" className="btn soft small" onClick={() => setVersioning(doc)}>Nueva versión</button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {uploading && <UploadModal code={code} onClose={() => setUploading(false)} />}
      {versioning && <VersionModal doc={versioning} code={code} onClose={() => setVersioning(null)} />}
    </>
  );
}

function FileField({ id, onPick, file, invalid }: { id: string; onPick: (file: File | null) => void; file: File | null; invalid?: boolean }) {
  return (
    <div className="field">
      <label htmlFor={id}>Archivo <span className="req">*</span></label>
      <input id={id} type="file" aria-invalid={invalid ? 'true' : undefined} onChange={(e) => onPick(e.target.files?.[0] ?? null)} />
      <div className="field-help">{file ? `${file.name} · ${formatBytes(file.size)}` : 'Elegí el archivo a cargar.'}</div>
      <div className="form-error">{invalid ? 'Elegí un archivo.' : ''}</div>
    </div>
  );
}

function UploadModal({ code, onClose }: { code: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const notify = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState('otro');
  const [title, setTitle] = useState('');
  const [classification, setClassification] = useState('internal');
  const [fileMissing, setFileMissing] = useState(false);

  const mutation = useMutation({
    mutationFn: (form: FormData) => documentsApi.upload(code, form),
    onSuccess: async () => {
      await invalidateCase(queryClient, code);
      notify('Documento cargado.');
      onClose();
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setFileMissing(true);
      return;
    }
    const form = new FormData();
    form.append('file', file);
    form.append('kind', kind);
    form.append('title', title.trim() || file.name);
    form.append('classification', classification);
    mutation.mutate(form);
  }

  return (
    <Modal
      title="Cargar documento"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn secondary" onClick={onClose}>Cancelar</button>
          <button type="submit" form="upload-doc-form" className="btn" disabled={mutation.isPending}>
            {mutation.isPending ? 'Cargando…' : 'Cargar'}
          </button>
        </>
      }
    >
      <form id="upload-doc-form" className="stack" noValidate onSubmit={submit}>
        {mutation.isError && <ErrorNotice error={mutation.error} />}
        <FileField id="doc-file" file={file} onPick={(f) => { setFile(f); setFileMissing(false); }} invalid={fileMissing} />
        <div className="field">
          <label htmlFor="doc-title">Título</label>
          <input id="doc-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Si lo dejás vacío se usa el nombre del archivo" />
        </div>
        <div className="fields-2">
          <div className="field">
            <label htmlFor="doc-kind">Tipo</label>
            <select id="doc-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
              {Object.entries(DOCUMENT_KINDS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="doc-class">Clasificación</label>
            <select id="doc-class" value={classification} onChange={(e) => setClassification(e.target.value)}>
              {Object.entries(CLASSIFICATION_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>
        </div>
      </form>
    </Modal>
  );
}

function VersionModal({ doc, code, onClose }: { doc: CaseDocument; code: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const notify = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [fileMissing, setFileMissing] = useState(false);

  const mutation = useMutation({
    mutationFn: (form: FormData) => documentsApi.uploadVersion(doc.id, form),
    onSuccess: async () => {
      await invalidateCase(queryClient, code);
      notify('Nueva versión cargada.');
      onClose();
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setFileMissing(true);
      return;
    }
    const form = new FormData();
    form.append('file', file);
    mutation.mutate(form);
  }

  return (
    <Modal
      title={`Nueva versión de ${doc.title}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn secondary" onClick={onClose}>Cancelar</button>
          <button type="submit" form="version-doc-form" className="btn" disabled={mutation.isPending}>
            {mutation.isPending ? 'Cargando…' : 'Cargar versión'}
          </button>
        </>
      }
    >
      <form id="version-doc-form" className="stack" noValidate onSubmit={submit}>
        {mutation.isError && <ErrorNotice error={mutation.error} />}
        <FileField id="version-file" file={file} onPick={(f) => { setFile(f); setFileMissing(false); }} invalid={fileMissing} />
      </form>
    </Modal>
  );
}
