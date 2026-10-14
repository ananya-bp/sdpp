"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { apiGet, apiPostFormWithProgress } from "../../lib/api";
import { useRequireAuth } from "../../lib/useRequireAuth";
import { documentTypeInfo, formatBytes } from "../../lib/status";
import { Alert, PageHeader, PageLoading } from "../components/ui";

// Fallbacks ONLY — used if GET /api/config/limits cannot be reached. The authoritative values
// come from the backend's centralized settings so the UI never keeps a conflicting copy.
const FALLBACK_LIMITS = {
  max_upload_mb: 5,
  max_upload_bytes: 5 * 1024 * 1024,
  max_files_per_application: 5,
  allowed_extensions: ["jpeg", "jpg", "pdf", "png"],
};

const extOf = (name) => (name.includes(".") ? name.split(".").pop().toLowerCase() : "");

// Map a backend field-spec input_type to an accessible control.
function FieldControl({ spec, value, onChange, error }) {
  const id = `detail-${spec.key}`;
  const describedBy = `${id}-help${error ? ` ${id}-err` : ""}`;
  return (
    <div className="form-field">
      <label htmlFor={id}>
        {spec.label}
        {spec.required && <span aria-hidden="true"> *</span>}
        {!spec.verified && (
          <span className="kle-badge" style={{ marginLeft: 8 }}>Unverified requirement</span>
        )}
      </label>
      {spec.input_type === "select" ? (
        <select id={id} value={value} onChange={(e) => onChange(e.target.value)}
          aria-describedby={describedBy} aria-invalid={Boolean(error)}>
          <option value="">— Select —</option>
          {spec.options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      ) : (
        <input id={id} type="text" value={value} maxLength={spec.max_length || 200}
          onChange={(e) => onChange(e.target.value)}
          aria-describedby={describedBy} aria-invalid={Boolean(error)} />
      )}
      {spec.help_text && <p id={`${id}-help`} className="hint">{spec.help_text}</p>}
      {error && <p id={`${id}-err`} className="field-error" role="alert">{error}</p>}
    </div>
  );
}

export default function ApplyPage() {
  const router = useRouter();
  const ready = useRequireAuth();
  const [docTypes, setDocTypes] = useState(null);
  const [typesError, setTypesError] = useState("");
  const [documentTypeId, setDocumentTypeId] = useState("");
  const [files, setFiles] = useState([]);
  const [messages, setMessages] = useState([]); // validation messages for rejected files
  const [submitError, setSubmitError] = useState("");
  const [fieldErrors, setFieldErrors] = useState({}); // server-side field-level errors by key
  const [details, setDetails] = useState({}); // request-specific form values
  const [limits, setLimits] = useState(FALLBACK_LIMITS);
  const [formSpecs, setFormSpecs] = useState(null); // GET /api/config/forms payload
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [dragging, setDragging] = useState(false);
  const submitting = useRef(false);

  useEffect(() => {
    if (!ready) return;
    apiGet("/api/document-types")
      .then((types) => {
        setDocTypes(types);
        if (types.length) setDocumentTypeId(String(types[0].id));
      })
      .catch((err) => setTypesError(err.message));
    // Dynamic limits & form specs (fail soft to fallbacks / no extra fields if unavailable).
    apiGet("/api/config/limits").then((l) => setLimits({ ...FALLBACK_LIMITS, ...l })).catch(() => {});
    apiGet("/api/config/forms").then((f) => setFormSpecs(f)).catch(() => {});
  }, [ready]);

  const selected = docTypes?.find((t) => String(t.id) === documentTypeId) || null;
  const spec = formSpecs?.forms?.find((f) => f.code === selected?.code) || null;

  function addFiles(incoming) {
    const problems = [];
    const next = [...files];
    const allowed = limits.allowed_extensions || FALLBACK_LIMITS.allowed_extensions;
    const maxBytes = limits.max_upload_bytes || limits.max_upload_mb * 1024 * 1024 || FALLBACK_LIMITS.max_upload_bytes;
    const maxFiles = limits.max_files_per_application ?? FALLBACK_LIMITS.max_files_per_application;
    const extList = allowed.map((e) => e.toUpperCase()).join(", ");
    for (const f of incoming) {
      if (!allowed.includes(extOf(f.name))) {
        problems.push(`“${f.name}” is not an accepted file type (${extList}).`);
      } else if (f.size > maxBytes) {
        problems.push(`“${f.name}” is larger than ${limits.max_upload_mb ?? Math.round(maxBytes / 1048576)} MB.`);
      } else if (f.size === 0) {
        problems.push(`“${f.name}” is empty.`);
      } else if (next.some((x) => x.name === f.name && x.size === f.size)) {
        problems.push(`“${f.name}” has already been added.`);
      } else if (next.length >= maxFiles) {
        problems.push(`“${f.name}” was not added: at most ${maxFiles} files per application.`);
      } else {
        next.push(f);
      }
    }
    setFiles(next);
    setMessages(problems);
  }

  function onPick(e) {
    addFiles(Array.from(e.target.files || []));
    e.target.value = ""; // allow picking the same file again after removing it
  }

  function onDrop(e) {
    e.preventDefault();
    setDragging(false);
    if (!busy) addFiles(Array.from(e.dataTransfer.files || []));
  }

  function removeFile(index) {
    setFiles(files.filter((_, i) => i !== index));
    setMessages([]);
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (submitting.current) return; // guards against double clicks / double Enter
    if (!documentTypeId) {
      setSubmitError("Please choose the document you want to apply for.");
      return;
    }
    if (files.length === 0) {
      setSubmitError("Please attach at least one supporting document before submitting.");
      return;
    }
    submitting.current = true;
    setSubmitError("");
    setFieldErrors({});
    setBusy(true);
    setProgress(0);
    try {
      const form = new FormData();
      form.append("document_type_id", documentTypeId);
      // Request-specific fields (GET /api/config/forms). Sent as JSON; backend re-validates.
      const cleanDetails = {};
      for (const [k, v] of Object.entries(details)) if (String(v || "").trim()) cleanDetails[k] = String(v).trim();
      form.append("details", JSON.stringify(cleanDetails));
      files.forEach((f) => form.append("files", f));
      const application = await apiPostFormWithProgress("/api/applications", form, setProgress);
      // Keep the form locked while navigating so the application cannot be submitted twice.
      router.push(`/applications/${application.id}?submitted=1`);
    } catch (err) {
      // 422 spec errors arrive as { detail: { errors: [...] } } — surface them per field where possible.
      const errs = err?.payload?.detail?.errors;
      if (Array.isArray(errs)) {
        const byKey = {};
        const general = [];
        for (const msg of errs) {
          const match = spec?.fields?.find((f) => msg.startsWith(f.label + " ") || msg.startsWith(`${f.label}:`) || msg.startsWith(`${f.label} is`));
          if (match) byKey[match.key] = msg; else general.push(msg);
        }
        setFieldErrors(byKey);
        setSubmitError(general.join(" "));
      } else {
        setSubmitError(err.message);
      }
      submitting.current = false;
      setBusy(false);
    }
  }

  if (!ready || (!docTypes && !typesError)) return <PageLoading label="Loading the application form…" />;
  if (typesError) {
    return (
      <main className="container narrow">
        <Alert title="The application form could not be loaded">{typesError}</Alert>
        <Link href="/dashboard" className="btn btn-secondary">Back to dashboard</Link>
      </main>
    );
  }

  const uploadDone = busy && progress >= 1;
  const allowedExts = limits.allowed_extensions || FALLBACK_LIMITS.allowed_extensions;
  const maxFiles = limits.max_files_per_application ?? FALLBACK_LIMITS.max_files_per_application;
  const maxMb = limits.max_upload_mb ?? FALLBACK_LIMITS.max_upload_mb;
  const extList = allowedExts.map((e) => e.toUpperCase()).join(", ");
  const missingDocs = spec ? spec.documents.filter((d) => d.required &&
    !files.some((f) => (["jpg", "jpeg"].includes(extOf(f.name)) ? ["jpg", "jpeg", "pdf", "png"].includes(d.code) : extOf(f.name) === d.code))) : [];

  return (
    <main className="container narrow kle-theme">
      <Link href="/dashboard" className="back-link">← Back to dashboard</Link>
      <PageHeader
        title="New application"
        subtitle="Choose a document and attach your supporting documents. We handle the rest."
      />

      <form onSubmit={onSubmit} noValidate>
        {submitError && <Alert title="Your application was not submitted">{submitError}</Alert>}

        <section className="card">
          <h2 style={{ marginBottom: 12 }}>1. Select a document</h2>
          <fieldset className="type-grid" disabled={busy}>
            <legend className="label" style={{ position: "absolute", left: -9999 }}>Document type</legend>
            {docTypes.map((t) => (
              <label key={t.id} className="type-option">
                <input type="radio" name="document_type" value={t.id}
                  checked={documentTypeId === String(t.id)}
                  onChange={(e) => { setDocumentTypeId(e.target.value); setFieldErrors({}); }} />
                <span className="box">
                  <strong>{t.name}</strong>
                  <span>{documentTypeInfo(t.code)}</span>
                </span>
              </label>
            ))}
          </fieldset>
        </section>

        {/* ---- request-specific details (from GET /api/config/forms) ---- */}
        {spec && spec.fields.length > 0 && (
          <section className="card">
            <h2 style={{ marginBottom: 6 }}>
              2. {spec.name} details{" "}
              {!spec.policy_verified && <span className="kle-badge">Unverified requirements</span>}
            </h2>
            {!spec.policy_verified && (
              <p className="hint" style={{ marginBottom: 12 }}>
                These fields follow the portal&apos;s working configuration, which has not yet been
                confirmed against official KLE Tech policy. Optional-looking required fields will not
                block your submission until the policy is verified.
              </p>
            )}
            {spec.fields.map((f) => (
              <FieldControl key={f.key} spec={f} value={details[f.key] || ""}
                error={fieldErrors[f.key]}
                onChange={(v) => setDetails((d) => ({ ...d, [f.key]: v }))} />
            ))}
          </section>
        )}

        <section className="card">
          <h2 style={{ marginBottom: 6 }}>{spec && spec.fields.length > 0 ? "3" : "2"}. Attach supporting documents</h2>
          <p className="muted small">
            At least one file is required{selected ? ` for ${selected.name}` : ""}. Your files are read
            automatically after submission, so please upload clear, legible scans or photos.
          </p>
          <ul className="checklist" style={{ marginBottom: 14 }}>
            <li>Accepted formats: {extList}</li>
            <li>Up to {maxFiles} files, {maxMb} MB each</li>
            <li>Make sure text is sharp and not cropped</li>
            {spec && spec.documents.map((d, i) => (
              <li key={`${d.code}-${i}`}>
                {d.label} {d.required ? "(required)" : "(optional)"}
                {!d.verified && <span className="kle-badge" style={{ marginLeft: 6 }}>Unverified</span>}
              </li>
            ))}
          </ul>
          {missingDocs.length > 0 && (
            <p className="field-error" role="status">
              Not attached yet: {missingDocs.map((d) => d.label).join("; ")}.
              {!spec.policy_verified && " (Checklist items marked unverified do not block submission.)"}
            </p>
          )}

          <label
            className={`dropzone ${dragging ? "drag" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <input type="file" multiple
              accept={allowedExts.map((e) => `.${e}`).join(",")}
              onChange={onPick} disabled={busy} />
            <strong>Choose files or drag them here</strong>
            <span className="muted small">{extList} · up to {maxMb} MB each · max {maxFiles} files</span>
          </label>

          {messages.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <Alert tone="warning" title="Some files were not added">
                <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                  {messages.map((m) => <li key={m}>{m}</li>)}
                </ul>
              </Alert>
            </div>
          )}

          {files.length > 0 ? (
            <ul className="file-items" aria-label="Selected files">
              {files.map((f, i) => (
                <li key={`${f.name}-${f.size}`}>
                  <div>
                    <div className="fname">{f.name}</div>
                    <div className="fmeta">{extOf(f.name).toUpperCase()} · {formatBytes(f.size)}</div>
                  </div>
                  <button type="button" className="link-btn" onClick={() => removeFile(i)}
                    disabled={busy} aria-label={`Remove ${f.name}`}>
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="hint">No files selected yet.</p>
          )}
        </section>

        <section className="card">
          {busy && (
            <div style={{ marginBottom: 14 }} aria-live="polite">
              <div className="small">
                {uploadDone ? "Upload complete — saving your application…" : `Uploading… ${Math.round(progress * 100)}%`}
              </div>
              <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100}
                aria-valuenow={Math.round(progress * 100)}>
                <div style={{ width: `${Math.round(progress * 100)}%` }} />
              </div>
            </div>
          )}
          <div className="btn-row">
            <button type="submit" className="btn btn-lg" disabled={busy}>
              {busy ? "Submitting…" : "Submit application"}
            </button>
            {!busy && <Link href="/dashboard" className="btn btn-secondary btn-lg">Cancel</Link>}
          </div>
          <p className="hint">
            After you submit, document reading and the eligibility check start automatically.
            You&apos;ll see the fee on the next page if you are eligible.
          </p>
        </section>
      </form>
    </main>
  );
}
