"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { apiGet, apiPostFormWithProgress } from "../../lib/api";
import { useRequireAuth } from "../../lib/useRequireAuth";
import { documentTypeInfo, formatBytes } from "../../lib/status";
import { Alert, PageHeader, PageLoading } from "../components/ui";

// These mirror the backend's upload rules (backend/app/services/uploads.py) for fast feedback only;
// the backend re-validates everything (including the file's real content type).
const MAX_FILES = 5;
const MAX_MB = 5;
const ALLOWED_EXT = ["pdf", "jpg", "jpeg", "png"];

const extOf = (name) => (name.includes(".") ? name.split(".").pop().toLowerCase() : "");

export default function ApplyPage() {
  const router = useRouter();
  const ready = useRequireAuth();
  const [docTypes, setDocTypes] = useState(null);
  const [typesError, setTypesError] = useState("");
  const [documentTypeId, setDocumentTypeId] = useState("");
  const [files, setFiles] = useState([]);
  const [messages, setMessages] = useState([]); // validation messages for rejected files
  const [submitError, setSubmitError] = useState("");
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
  }, [ready]);

  function addFiles(incoming) {
    const problems = [];
    const next = [...files];
    for (const f of incoming) {
      if (!ALLOWED_EXT.includes(extOf(f.name))) {
        problems.push(`“${f.name}” is not a PDF, JPG or PNG file.`);
      } else if (f.size > MAX_MB * 1024 * 1024) {
        problems.push(`“${f.name}” is larger than ${MAX_MB} MB.`);
      } else if (f.size === 0) {
        problems.push(`“${f.name}” is empty.`);
      } else if (next.some((x) => x.name === f.name && x.size === f.size)) {
        problems.push(`“${f.name}” has already been added.`);
      } else if (next.length >= MAX_FILES) {
        problems.push(`“${f.name}” was not added: at most ${MAX_FILES} files per application.`);
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
    setBusy(true);
    setProgress(0);
    try {
      const form = new FormData();
      form.append("document_type_id", documentTypeId);
      files.forEach((f) => form.append("files", f));
      const application = await apiPostFormWithProgress("/api/applications", form, setProgress);
      // Keep the form locked while navigating so the application cannot be submitted twice.
      router.push(`/applications/${application.id}?submitted=1`);
    } catch (err) {
      setSubmitError(err.message);
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

  const selected = docTypes.find((t) => String(t.id) === documentTypeId);
  const uploadDone = busy && progress >= 1;

  return (
    <main className="container narrow">
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
                  onChange={(e) => setDocumentTypeId(e.target.value)} />
                <span className="box">
                  <strong>{t.name}</strong>
                  <span>{documentTypeInfo(t.code)}</span>
                </span>
              </label>
            ))}
          </fieldset>
        </section>

        <section className="card">
          <h2 style={{ marginBottom: 6 }}>2. Attach supporting documents</h2>
          <p className="muted small">
            At least one file is required{selected ? ` for ${selected.name}` : ""}. Your files are read
            automatically after submission, so please upload clear, legible scans or photos.
          </p>
          <ul className="checklist" style={{ marginBottom: 14 }}>
            <li>Accepted formats: PDF, JPG or PNG</li>
            <li>Up to {MAX_FILES} files, {MAX_MB} MB each</li>
            <li>Make sure text is sharp and not cropped</li>
          </ul>

          <label
            className={`dropzone ${dragging ? "drag" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png" onChange={onPick} disabled={busy} />
            <strong>Choose files or drag them here</strong>
            <span className="muted small">PDF, JPG or PNG · up to {MAX_MB} MB each</span>
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
