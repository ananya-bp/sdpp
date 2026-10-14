"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiGet } from "../lib/api";
import { getToken } from "../lib/auth";
import { documentTypeInfo } from "../lib/status";

const STEPS = [
  ["Submit your application", "Choose the document you need and upload your supporting documents."],
  ["Documents are read automatically", "Text and key details are extracted from your uploads — no extra clicks."],
  ["Eligibility is checked", "The application is checked against the rules for the document you requested."],
  ["Pay and track progress", "Pay the fee (sandbox in this prototype) and follow every status change on a timeline."],
];

export default function HomePage() {
  const [signedIn, setSignedIn] = useState(false);
  const [types, setTypes] = useState({ state: "loading", items: [] });

  useEffect(() => {
    setSignedIn(Boolean(getToken()));
    apiGet("/api/document-types")
      .then((items) => setTypes({ state: "ok", items }))
      .catch(() => setTypes({ state: "error", items: [] }));
  }, []);

  return (
    <>
      <section className="hero">
        <div className="hero-inner">
          <div>
            {/* Student-facing KLE branding: original logo PNG, aspect ratio preserved. */}
            <img src="/logo.png" alt="KLE Technological University logo" width={400} height={70}
              style={{ height: 56, width: "auto", maxWidth: "90%", marginBottom: 14 }} />
            <p className="eyebrow" style={{ color: "#f2c9cb" }}>KLE Tech · Academic document services</p>
            <h1>Request your academic documents online</h1>
            <p className="lead">
              Apply for transcripts, certificates and grade cards in one place. Upload your
              supporting documents once and follow your application from submission to completion.
            </p>
            <div className="btn-row">
              {signedIn ? (
                <>
                  <Link href="/apply" className="btn btn-light btn-lg">Start a new application</Link>
                  <Link href="/dashboard" className="btn btn-outline-light btn-lg">Go to dashboard</Link>
                </>
              ) : (
                <>
                  <Link href="/register" className="btn btn-light btn-lg">Register to apply</Link>
                  <Link href="/login" className="btn btn-outline-light btn-lg">Sign in</Link>
                </>
              )}
            </div>
          </div>
          <aside className="hero-panel" aria-label="What happens after you apply">
            <h2>After you submit</h2>
            <ol>
              <li>Your documents are read automatically</li>
              <li>Eligibility is checked for you</li>
              <li>You see the fee and pay (sandbox)</li>
              <li>Every status change is recorded on your timeline</li>
            </ol>
          </aside>
        </div>
      </section>

      <main className="container">
        <section className="section" style={{ marginTop: 0 }}>
          <h2>Documents you can request</h2>
          <p className="muted">Select any of these when you start an application.</p>
          {types.state === "loading" && (
            <div className="grid grid-4">
              {[0, 1, 2, 3].map((i) => <div key={i} className="skeleton" />)}
            </div>
          )}
          {types.state === "error" && (
            <p className="muted">
              The list of documents could not be loaded right now. You can still{" "}
              <Link href={signedIn ? "/apply" : "/login"}>{signedIn ? "start an application" : "sign in"}</Link>.
            </p>
          )}
          {types.state === "ok" && (
            <div className="grid grid-4">
              {types.items.map((t) => (
                <div key={t.id} className="tile">
                  <h3>{t.name}</h3>
                  <p>{documentTypeInfo(t.code)}</p>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="section">
          <h2>How it works</h2>
          <p className="muted">From application to payment in four steps.</p>
          <div className="grid grid-4">
            {STEPS.map(([title, text], i) => (
              <div key={title} className="tile">
                <span className="step-no">{i + 1}</span>
                <h3>{title}</h3>
                <p>{text}</p>
              </div>
            ))}
          </div>
        </section>

        <div className="notice-strip">
          <strong>Prototype notice:</strong> this portal is a college project. Student records and
          applications are simulated, and the payment step is a sandbox that moves no real money.
        </div>
      </main>
    </>
  );
}
