import { statusTone } from "../../lib/status";

export function PageHeader({ eyebrow, title, subtitle, actions }) {
  return (
    <header className="page-header">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {subtitle && <p className="subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </header>
  );
}

export function Alert({ tone = "danger", title, children, action }) {
  return (
    <div className={`alert alert-${tone}`} role={tone === "danger" ? "alert" : "status"}>
      <div className="alert-body">
        {title && <strong>{title}</strong>}
        {children && <div>{children}</div>}
      </div>
      {action}
    </div>
  );
}

export function Spinner({ label }) {
  return (
    <span className="spinner-wrap" role="status">
      <span className="spinner" aria-hidden="true" />
      {label && <span>{label}</span>}
    </span>
  );
}

export function PageLoading({ label = "Loading…" }) {
  return (
    <main className="container narrow">
      <div className="card center-card">
        <Spinner label={label} />
      </div>
    </main>
  );
}

export function StatusPill({ status, label }) {
  return <span className={`pill pill-${statusTone(status)}`}>{label || status}</span>;
}

export function EmptyState({ title, children, action }) {
  return (
    <div className="empty-state">
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}
