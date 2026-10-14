// Presentation helpers for application statuses. The status VOCABULARY and labels come from the
// backend (backend/app/core/statuses.py, returned as `status_label`); this file only maps a status
// to a colour tone and never decides eligibility or any workflow outcome.
const SUCCESS = new Set(["ELIGIBLE", "PAYMENT_COMPLETED", "VERIFIED", "DOCUMENT_GENERATED"]);
const DANGER = new Set(["NOT_ELIGIBLE", "REJECTED"]);
const WARNING = new Set(["PAYMENT_PENDING"]);

export function statusTone(status) {
  if (SUCCESS.has(status)) return "success";
  if (DANGER.has(status)) return "danger";
  if (WARNING.has(status)) return "warning";
  if (status === "SUBMITTED" || status === "OCR_COMPLETED" || status === "UNDER_REVIEW") return "info";
  return "neutral";
}

// Plain-language descriptions of the document types (keyed by the backend's stable `code`).
// Generic definitions only - no fees, deadlines or policy claims.
export const DOCUMENT_TYPE_INFO = {
  TRANSCRIPT: "A record of the courses you have taken and the grades you earned.",
  MIGRATION_CERTIFICATE: "A certificate for students transferring to another institution or university.",
  DUPLICATE_GRADE_CARD: "A replacement copy of a grade card that was lost or damaged.",
  PROVISIONAL_DEGREE_CERTIFICATE: "Interim proof of degree completion, issued before the final certificate.",
};

export function documentTypeInfo(code) {
  return DOCUMENT_TYPE_INFO[code] || "Request this academic document through the portal.";
}

export function formatBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(iso) {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function formatDateTime(iso) {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function formatRupees(amount) {
  if (amount === null || amount === undefined) return "—";
  return `₹${Number(amount).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
