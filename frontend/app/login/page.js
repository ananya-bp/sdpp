"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiPostJson } from "../../lib/api";
import { setToken } from "../../lib/auth";
import { Alert, PageHeader } from "../components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    if (busy) return;
    setError("");
    setBusy(true);
    try {
      const { access_token } = await apiPostJson("/api/auth/login", { email, password });
      setToken(access_token);
      router.push("/dashboard");
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <main className="container auth">
      <PageHeader title="Sign in" subtitle="Access your applications and track their progress." />
      <form className="card" onSubmit={onSubmit}>
        {error && <Alert title="Could not sign in">{error}</Alert>}

        <label htmlFor="email">Email address</label>
        <input id="email" type="email" autoComplete="email" value={email}
          onChange={(e) => setEmail(e.target.value)} required />

        <label htmlFor="password">Password</label>
        <input id="password" type="password" autoComplete="current-password" value={password}
          onChange={(e) => setPassword(e.target.value)} required />

        <div className="form-actions">
          <button type="submit" className="btn btn-lg" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </div>
        <p className="auth-foot">
          New here? <Link href="/register">Create an account</Link>
        </p>
      </form>
    </main>
  );
}
