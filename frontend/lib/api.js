import { clearToken, getToken } from "./auth";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

const NETWORK_MESSAGE =
  "Could not reach the server. Check your connection and that the portal backend is running, then try again.";

// isAuthenticatedCall: true for requests that sent a bearer token. A 401 on one of
// those means the session expired, so we clear it and redirect to /login. A 401 on a
// public call (login, register) just means "wrong credentials" / "not found" and must
// be shown as an inline form error instead, not treated as a session expiring.
async function handle(res, isAuthenticatedCall) {
  if (res.status === 401 && isAuthenticatedCall) {
    clearToken();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new ApiError(401, "Your session has expired. Please sign in again.");
  }
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail) && body.detail[0]?.msg) message = body.detail[0].msg;
    } catch {
      /* response had no JSON body */
    }
    throw new ApiError(res.status, message);
  }
  return res.status === 204 ? null : res.json();
}

async function send(url, init, isAuthenticatedCall) {
  let res;
  try {
    res = await fetch(url, init);
  } catch {
    throw new ApiError(0, NETWORK_MESSAGE);
  }
  return handle(res, isAuthenticatedCall);
}

export function apiGet(path, { auth = false } = {}) {
  const headers = {};
  if (auth) headers.Authorization = `Bearer ${getToken()}`;
  return send(`${API_BASE_URL}${path}`, { cache: "no-store", headers }, auth);
}

// Public POST with a JSON body (login / register): never redirects on 401.
export function apiPostJson(path, body) {
  return send(
    `${API_BASE_URL}${path}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    false,
  );
}

// Authenticated POST with an optional JSON body (application actions: process, payment ...).
export function apiPostAuth(path, body) {
  return send(
    `${API_BASE_URL}${path}`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${getToken()}`,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    },
    true,
  );
}

// Multipart upload with progress. fetch() cannot report upload progress, so this uses XHR.
// onProgress receives a fraction 0..1 of the request body that has been sent.
export function apiPostFormWithProgress(path, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}${path}`);
    xhr.setRequestHeader("Authorization", `Bearer ${getToken()}`);
    xhr.responseType = "json";
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.onerror = () => reject(new ApiError(0, NETWORK_MESSAGE));
    xhr.onabort = () => reject(new ApiError(0, "The upload was cancelled."));
    xhr.onload = () => {
      const body = xhr.response;
      if (xhr.status === 401) {
        clearToken();
        window.location.href = "/login";
        reject(new ApiError(401, "Your session has expired. Please sign in again."));
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body);
        return;
      }
      let message = `Request failed (${xhr.status})`;
      if (body && typeof body.detail === "string") message = body.detail;
      else if (body && Array.isArray(body.detail) && body.detail[0]?.msg) message = body.detail[0].msg;
      reject(new ApiError(xhr.status, message));
    };
    xhr.send(formData);
  });
}
