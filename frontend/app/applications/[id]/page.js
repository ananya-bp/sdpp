"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPostAuth } from "../../../lib/api";
import { useRequireAuth } from "../../../lib/useRequireAuth";
import { formatBytes, formatDate, formatDateTime, formatRupees } from "../../../lib/status";
import { Alert, PageLoading, Spinner, StatusPill } from "../../components/ui";

const POLL_MS = 1500;
const MAX_POLLS = 80; // ~2 minutes: polling only runs while a processing request is in flight, and is capped

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const PAID_OR_LATER = ["PAYMENT_COMPLETED", "UNDER_REVIEW", "VERIFIED", "REJECTED", "DOCUMENT_GENERATED"];

// ---- derived view state (display only: every outcome below comes from the backend's data) ----

const ocrSucceededForAll = (app) =>
  app.documents.every((d) => d.ocr_result && d.ocr_result.status === "SUCCESS");

const ocrHasFailure = (app) => app.documents.some((d) => d.ocr_result?.status === "FAILED");

// Should this page start automatic processing on load? Only from the two states the backend's
// /process endpoint can advance: SUBMITTED, or OCR_COMPLETED where every file was read fine.
function needsAutoProcessing(app) {
  if (app.status === "SUBMITTED") return true;
  return app.status === "OCR_COMPLETED" && ocrSucceededForAll(app);
}

function latestEligibilityEntry(app) {
  for (let i = app.history.length - 1; i >= 0; i--) {
    if (["ELIGIBLE", "NOT_ELIGIBLE"].includes(app.history[i].status)) return app.history[i];
  }
  return null;
}

function hasPendingTransaction(app) {
  return app.transactions.some((t) => t.payment_status === "PENDING");
}

function buildSteps(app, processing, processError) {
  const s = app.status;
  const ocrBad = s === "OCR_COMPLETED" && ocrHasFailure(app);
  const steps = [];

  steps.push({ title: "Application submitted", state: "done", detail: formatDateTime(app.submitted_at) });

  if (s === "SUBMITTED") {
    steps.push({
      title: "Extracting document information",
      state: processError ? "error" : "active",
      detail: processError ? "Processing could not be completed" : "Reading your uploaded documents…",
    });
  } else if (ocrBad) {
    steps.push({ title: "Extracting document information", state: "error", detail: "Some documents could not be read" });
  } else {
    steps.push({ title: "Extracting document information", state: "done", detail: "Documents processed" });
  }

  if (s === "SUBMITTED" || ocrBad) {
    steps.push({ title: "Checking eligibility", state: "pending", detail: "Waits for document processing" });
  } else if (s === "OCR_COMPLETED") {
    steps.push({
      title: "Checking eligibility",
      state: processError ? "error" : "active",
      detail: processError ? "Processing could not be completed" : "Checking against the eligibility rules…",
    });
  } else if (s === "NOT_ELIGIBLE") {
    steps.push({ title: "Checking eligibility", state: "error", detail: "Not eligible" });
  } else {
    steps.push({ title: "Checking eligibility", state: "done", detail: "Eligible" });
  }

  if (s === "ELIGIBLE") steps.push({ title: "Payment", state: "action", detail: "Action needed: pay the fee" });
  else if (s === "PAYMENT_PENDING") steps.push({ title: "Payment", state: "action", detail: "Payment not completed yet" });
  else if (PAID_OR_LATER.includes(s)) steps.push({ title: "Payment", state: "done", detail: "Payment received (sandbox)" });
  else if (s === "NOT_ELIGIBLE") steps.push({ title: "Payment", state: "pending", detail: "Not available for this application" });
  else steps.push({ title: "Payment", state: "pending", detail: "Available once you are eligible" });

  if (s === "UNDER_REVIEW") steps.push({ title: "Review and issue", state: "active", detail: "Under review" });
  else if (s === "VERIFIED" || s === "DOCUMENT_GENERATED") steps.push({ title: "Review and issue", state: "done", detail: app.status_label });
  else if (s === "REJECTED") steps.push({ title: "Review and issue", state: "error", detail: "Rejected" });
  else steps.push({ title: "Review and issue", state: "pending", detail: "Not part of this prototype yet" });

  return steps;
}

function StepDot({ state, index }) {
  if (state === "done") return <span className="step-dot" aria-hidden="true">✓</span>;
  if (state === "error") return <span className="step-dot" aria-hidden="true">✕</span>;
  if (state === "action") return <span className="step-dot" aria-hidden="true">!</span>;
  if (state === "active") return <span className="step-dot" aria-hidden="true"><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /></span>;
  return <span className="step-dot" aria-hidden="true">{index + 1}</span>;
}

const STATE_TEXT = { done: "completed", active: "in progress", action: "action needed", error: "problem", pending: "not started" };

// ---- page ----

export default function ApplicationDetailPage() {
  const { id } = useParams();
  const ready = useRequireAuth();

  const [app, setApp] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [processing, setProcessing] = useState(false);
  const [processError, setProcessError] = useState("");
  const [payBusy, setPayBusy] = useState(false);
  const [payError, setPayError] = useState("");
  const [payNotice, setPayNotice] = useState(null);
  const [justSubmitted, setJustSubmitted] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const mounted = useRef(true);
  const autoStarted = useRef(false); // automatic processing starts at most once per page visit
  const processInFlight = useRef(false);
  const payInFlight = useRef(false);

  // OCR -> eligibility via the backend's /process endpoint (idempotent, serialised per application).
  // While the request is in flight we poll the real application record so the student sees each
  // genuine status change; polling stops as soon as the request returns (and is capped).
  const runProcessing = useCallback(
    async ({ retry = false } = {}) => {
      if (processInFlight.current) return;
      processInFlight.current = true;
      setProcessing(true);
      setProcessError("");
      let stopped = false;
      (async () => {
        for (let i = 0; i < MAX_POLLS && !stopped; i++) {
          await sleep(POLL_MS);
          if (stopped) break;
          try {
            const fresh = await apiGet(`/api/applications/${id}`, { auth: true });
            if (!stopped && mounted.current) setApp(fresh);
          } catch {
            /* a missed poll is harmless: the main request below reports real failures */
          }
        }
      })();
      try {
        const updated = await apiPostAuth(`/api/applications/${id}/process${retry ? "?retry_ocr=true" : ""}`);
        if (mounted.current) setApp(updated);
      } catch (err) {
        if (mounted.current) setProcessError(err.message);
      } finally {
        stopped = true;
        processInFlight.current = false;
        if (mounted.current) setProcessing(false);
      }
    },
    [id],
  );

  useEffect(() => {
    if (!ready) return;
    mounted.current = true;
    setJustSubmitted(new URLSearchParams(window.location.search).get("submitted") === "1");
    apiGet(`/api/applications/${id}`, { auth: true })
      .then((a) => {
        if (!mounted.current) return;
        setApp(a);
        if (!autoStarted.current && needsAutoProcessing(a)) {
          autoStarted.current = true;
          runProcessing();
        }
      })
      .catch((err) => mounted.current && setLoadError(err.message));
    return () => {
      mounted.current = false;
    };
  }, [ready, id, runProcessing]);

  async function refresh() {
    if (refreshing || processInFlight.current) return;
    setRefreshing(true);
    try {
      setApp(await apiGet(`/api/applications/${id}`, { auth: true }));
    } catch (err) {
      setLoadError(err.message);
    } finally {
      setRefreshing(false);
    }
  }

  // Explicit, student-initiated payment actions only. Never called automatically.
  async function payAction(path, body, notice) {
    if (payInFlight.current) return;
    payInFlight.current = true;
    setPayBusy(true);
    setPayError("");
    setPayNotice(null);
    try {
      const updated = await apiPostAuth(`/api/applications/${id}${path}`, body);
      setApp(updated);
      if (notice) setPayNotice(notice(updated));
    } catch (err) {
      setPayError(err.message);
    } finally {
      payInFlight.current = false;
      setPayBusy(false);
    }
  }

  if (loadError && !app) {
    return (
      <main className="container narrow">
        <Alert title="We couldn't open this application">{loadError}</Alert>
        <Link href="/dashboard" className="btn btn-secondary">Back to dashboard</Link>
      </main>
    );
  }
  if (!ready || !app) return <PageLoading label="Loading application…" />;

  const s = app.status;
  const steps = buildSteps(app, processing, processError);
  const eligibility = latestEligibilityEntry(app);
  const ocrBad = s === "OCR_COMPLETED" && ocrHasFailure(app);
  const pending = hasPendingTransaction(app);
  const lastTxn = app.transactions[app.transactions.length - 1];
  const lastFailed = lastTxn && lastTxn.payment_status === "FAILED";
  const successTxn = app.transactions.find((t) => t.payment_status === "SUCCESS");
  const payable = s === "ELIGIBLE" || s === "PAYMENT_PENDING";
  const reasons = s === "NOT_ELIGIBLE" && eligibility?.note ? eligibility.note.split("; ") : [];
  const stuck = !processing && processError; // processing failed unexpectedly (not a per-file OCR failure)

  return (
    <main className="container">
      <Link href="/dashboard" className="back-link">← Back to dashboard</Link>
      <header className="page-header">
        <div>
          <p className="eyebrow">Application #{app.id}</p>
          <h1>{app.document_type.name}</h1>
          <p className="subtitle">Submitted {formatDateTime(app.submitted_at)}</p>
        </div>
        <StatusPill status={s} label={app.status_label} />
      </header>

      {justSubmitted && (
        <Alert tone="success" title="Application submitted">
          Your application and {app.documents.length} document{app.documents.length === 1 ? "" : "s"} were saved.
          We&apos;re now processing them automatically — you don&apos;t need to do anything.
        </Alert>
      )}

      <div className="detail-layout">
        {/* ---------- main column ---------- */}
        <div>
          <section className="card" aria-live="polite">
            <div className="card-head">
              <h2>Progress</h2>
              {processing && <Spinner label="Processing…" />}
            </div>
            <ol className="stepper">
              {steps.map((st, i) => (
                <li key={st.title} className={st.state}>
                  <StepDot state={st.state} index={i} />
                  <div>
                    <div className="step-title">
                      {st.title} <span className="sr-only">({STATE_TEXT[st.state]})</span>
                    </div>
                    <div className="step-detail">{st.detail}</div>
                  </div>
                </li>
              ))}
            </ol>
          </section>

          {/* processing problems */}
          {stuck && (
            <Alert title="Processing could not be completed" action={
              <button className="btn btn-sm" onClick={() => runProcessing()} disabled={processing}>Try again</button>
            }>
              {processError} Your application and uploaded documents are safe.
            </Alert>
          )}
          {ocrBad && !processing && (
            <Alert title="Some of your documents could not be read" action={
              <button className="btn btn-sm" onClick={() => runProcessing({ retry: true })} disabled={processing}>
                Retry document processing
              </button>
            }>
              Your application and files are saved. The eligibility check waits until every document has been read.
              You can retry now; if it keeps failing, submit a new application with clearer PDF, JPG or PNG files.
            </Alert>
          )}

          {/* eligibility outcome (the backend's decision and explanation) */}
          {eligibility && (
            <section className="card">
              <div className="card-head">
                <h2>Eligibility</h2>
                <StatusPill status={eligibility.status} label={eligibility.status === "ELIGIBLE" ? "Eligible" : "Not eligible"} />
              </div>
              {s === "NOT_ELIGIBLE" ? (
                <>
                  <p>This application is not eligible, so payment is not available. Reason{reasons.length === 1 ? "" : "s"}:</p>
                  <ul className="reason-list">
                    {reasons.map((r) => <li key={r}>{r}</li>)}
                  </ul>
                  <p className="hint" style={{ marginTop: 12 }}>
                    Eligibility rules in this prototype are a placeholder policy, not an official university policy.
                  </p>
                </>
              ) : (
                <>
                  <p style={{ marginBottom: 0 }}>All eligibility conditions were met for this document.</p>
                  <p className="hint">Eligibility rules in this prototype are a placeholder policy, not an official university policy.</p>
                </>
              )}
            </section>
          )}

          {/* fee + payment */}
          {(payable || successTxn || app.transactions.length > 0) && s !== "NOT_ELIGIBLE" && (
            <section className="card">
              <div className="card-head">
                <h2>Fee and payment</h2>
                <span className="sandbox-tag">Sandbox payment</span>
              </div>

              <div className="fee-box">
                <span>Fee for {app.document_type.name}</span>
                <span className="amount">{formatRupees(successTxn?.amount ?? lastTxn?.amount ?? app.fee_amount)}</span>
              </div>

              {payError && <Alert title="Payment action failed">{payError}</Alert>}
              {payNotice && <Alert tone={payNotice.tone} title={payNotice.title}>{payNotice.text}</Alert>}

              {s === "ELIGIBLE" && (
                <>
                  <p className="muted">
                    You are eligible. This is a sandbox: no real payment gateway is used and no money moves.
                  </p>
                  <button className="btn" disabled={payBusy}
                    onClick={() => payAction("/payment/initiate")}>
                    {payBusy ? "Starting…" : "Proceed to sandbox payment"}
                  </button>
                </>
              )}

              {s === "PAYMENT_PENDING" && pending && (
                <>
                  <p className="muted">
                    Sandbox gateway: choose the result to simulate. Nothing is charged and no real bank is contacted.
                  </p>
                  <div className="btn-row">
                    <button className="btn" disabled={payBusy}
                      onClick={() => payAction("/payment/complete", { outcome: "success" }, () => ({
                        tone: "success", title: "Payment successful", text: "The sandbox payment was recorded.",
                      }))}>
                      {payBusy ? "Processing…" : "Simulate successful payment"}
                    </button>
                    <button className="btn btn-danger-outline" disabled={payBusy}
                      onClick={() => payAction("/payment/complete", { outcome: "failure" }, () => ({
                        tone: "danger", title: "Payment failed", text: "The simulated payment failed. You can try again.",
                      }))}>
                      Simulate failed payment
                    </button>
                  </div>
                </>
              )}

              {s === "PAYMENT_PENDING" && !pending && (
                <>
                  <p className="muted">
                    {lastFailed ? "Your last payment attempt failed. Nothing was charged. You can start a new attempt." : "Start a new payment attempt."}
                  </p>
                  <button className="btn" disabled={payBusy}
                    onClick={() => payAction("/payment/initiate")}>
                    {payBusy ? "Starting…" : "Retry payment"}
                  </button>
                </>
              )}

              {PAID_OR_LATER.includes(s) && (
                <Alert tone="success" title="Payment received (sandbox)">
                  The sandbox payment succeeded. Current status: <strong>{app.status_label}</strong>. Administrative
                  review and document issue are not part of this prototype yet, so no further action is needed here.
                </Alert>
              )}

              {app.transactions.length > 0 && (
                <div style={{ overflowX: "auto" }}>
                  <table className="txn-table">
                    <thead><tr><th>Attempt</th><th>When</th><th>Amount</th><th>Result</th></tr></thead>
                    <tbody>
                      {app.transactions.map((t, i) => (
                        <tr key={t.id}>
                          <td>#{i + 1}</td>
                          <td>{formatDateTime(t.transacted_at)}</td>
                          <td>{formatRupees(t.amount)}</td>
                          <td>
                            <span className={`pill pill-${t.payment_status === "SUCCESS" ? "success" : t.payment_status === "FAILED" ? "danger" : "warning"}`}>
                              {t.payment_status === "SUCCESS" ? "Successful" : t.payment_status === "FAILED" ? "Failed" : "Awaiting result"}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}

          {/* documents + OCR results */}
          <section className="card">
            <h2 style={{ marginBottom: 14 }}>Submitted documents</h2>
            {app.documents.length === 0 ? (
              <p className="muted">No files were uploaded with this application.</p>
            ) : (
              app.documents.map((d) => {
                const r = d.ocr_result;
                const f = r?.extracted_fields;
                return (
                  <div key={d.id} className="doc-item">
                    <div className="doc-top">
                      <div>
                        <div className="doc-name">{d.original_filename}</div>
                        <div className="doc-meta">{formatBytes(d.size_bytes)} · uploaded {formatDateTime(d.uploaded_at)}</div>
                      </div>
                      {!r ? (
                        <span className="pill pill-neutral">{processing ? "Reading…" : "Waiting"}</span>
                      ) : r.status === "SUCCESS" ? (
                        <span className="pill pill-success">Information extracted</span>
                      ) : (
                        <span className="pill pill-danger">Could not be read</span>
                      )}
                    </div>
                    {r?.status === "FAILED" && (
                      <p className="small muted" style={{ margin: "8px 0 0" }}>
                        This file could not be processed ({r.error_message || "unreadable file"}).
                      </p>
                    )}
                    {r?.status === "SUCCESS" && (
                      <>
                        <div className="fields">
                          <span>Words found: <b>{f?.word_count ?? 0}</b></span>
                          <span>USN: <b>{f?.detected_usns?.length ? f.detected_usns.join(", ") : "not detected"}</b></span>
                          <span>CGPA-like values: <b>{f?.detected_cgpa_like_numbers?.length ? f.detected_cgpa_like_numbers.join(", ") : "none"}</b></span>
                          <span>Dates: <b>{f?.detected_dates?.length ? f.detected_dates.join(", ") : "none"}</b></span>
                        </div>
                        {r.raw_text ? (
                          <details className="ocr-text">
                            <summary>View extracted text</summary>
                            <pre>{r.raw_text}</pre>
                          </details>
                        ) : (
                          <p className="small muted" style={{ margin: "8px 0 0" }}>No text was detected in this file.</p>
                        )}
                      </>
                    )}
                  </div>
                );
              })
            )}
          </section>
        </div>

        {/* ---------- side column ---------- */}
        <aside>
          <section className="card">
            <h2 style={{ marginBottom: 14 }}>Application summary</h2>
            <dl className="summary-list">
              <dt>Application</dt><dd>#{app.id}</dd>
              <dt>Document</dt><dd>{app.document_type.name}</dd>
              <dt>Submitted</dt><dd>{formatDate(app.submitted_at)}</dd>
              <dt>Status</dt><dd><StatusPill status={s} label={app.status_label} /></dd>
              <dt>Documents</dt><dd>{app.documents.length} file{app.documents.length === 1 ? "" : "s"}</dd>
              <dt>Fee (sandbox)</dt><dd>{formatRupees(app.fee_amount)}</dd>
            </dl>
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Status timeline</h2>
              <button className="btn btn-secondary btn-sm" onClick={refresh} disabled={refreshing || processing}>
                {refreshing ? "Refreshing…" : "Refresh"}
              </button>
            </div>
            <ol className="timeline">
              {app.history.map((h, i) => (
                <li key={i}>
                  <div className="t-title">{h.status_label}</div>
                  {h.note && <div className="t-note">{h.note}</div>}
                  <div className="t-when">{formatDateTime(h.changed_at)}</div>
                </li>
              ))}
            </ol>
          </section>
        </aside>
      </div>
    </main>
  );
}
