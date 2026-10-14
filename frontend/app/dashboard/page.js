"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiGet } from "../../lib/api";
import { useRequireAuth } from "../../lib/useRequireAuth";
import { formatDate } from "../../lib/status";
import { Alert, EmptyState, PageHeader, PageLoading, StatusPill } from "../components/ui";

export default function DashboardPage() {
  const ready = useRequireAuth();
  const [me, setMe] = useState(null);
  const [apps, setApps] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    Promise.all([apiGet("/api/auth/me", { auth: true }), apiGet("/api/applications", { auth: true })])
      .then(([meData, appsData]) => {
        setMe(meData);
        setApps(appsData);
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  if (!ready) return <PageLoading />;
  if (error) {
    return (
      <main className="container narrow">
        <Alert title="We couldn't load your dashboard"
          action={<button className="btn btn-secondary btn-sm" onClick={load}>Try again</button>}>
          {error}
        </Alert>
      </main>
    );
  }
  if (!me || !apps) return <PageLoading label="Loading your applications…" />;

  const student = me.student;
  const inProgress = apps.filter((a) => !["VERIFIED", "REJECTED", "NOT_ELIGIBLE", "DOCUMENT_GENERATED"].includes(a.status)).length;
  const recent = apps.slice(0, 10);

  return (
    <main className="container">
      <PageHeader
        eyebrow="Student dashboard"
        title={`Welcome, ${student?.full_name || me.email}`}
        subtitle={student ? `${student.usn} · ${student.department} · Semester ${student.semester}` : undefined}
        actions={<Link href="/apply" className="btn btn-lg">New application</Link>}
      />

      <div className="stat-row">
        <div className="stat"><div className="num">{apps.length}</div><div className="lbl">Total applications</div></div>
        <div className="stat"><div className="num">{inProgress}</div><div className="lbl">In progress</div></div>
        <div className="stat"><div className="num">{apps.length - inProgress}</div><div className="lbl">Concluded</div></div>
      </div>

      <section className="card">
        <div className="card-head">
          <h2>Recent applications</h2>
          {apps.length > recent.length && <span className="muted small">Showing the latest {recent.length}</span>}
        </div>

        {apps.length === 0 ? (
          <EmptyState
            title="No applications yet"
            action={<Link href="/apply" className="btn">Start your first application</Link>}
          >
            Choose a document, upload your supporting files and we&apos;ll take it from there.
          </EmptyState>
        ) : (
          <>
            <table className="app-table">
              <thead>
                <tr><th>Document</th><th>Submitted</th><th>Status</th><th /></tr>
              </thead>
              <tbody>
                {recent.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <strong>{a.document_type.name}</strong>
                      <div className="ref">Application #{a.id}</div>
                    </td>
                    <td>{formatDate(a.submitted_at)}</td>
                    <td><StatusPill status={a.status} label={a.status_label} /></td>
                    <td style={{ textAlign: "right" }}>
                      <Link href={`/applications/${a.id}`} className="btn btn-secondary btn-sm">View details</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="app-cards">
              {recent.map((a) => (
                <Link key={a.id} href={`/applications/${a.id}`} className="app-card">
                  <div className="top">
                    <strong>{a.document_type.name}</strong>
                    <StatusPill status={a.status} label={a.status_label} />
                  </div>
                  <div className="muted small">Application #{a.id} · {formatDate(a.submitted_at)}</div>
                </Link>
              ))}
            </div>
          </>
        )}
      </section>
    </main>
  );
}
