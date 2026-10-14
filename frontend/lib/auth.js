// Minimal client-side auth: the JWT lives in localStorage (a demo/portfolio choice — a
// production app would use an httpOnly cookie set by the server instead).
const KEY = "sdp_token";

export function getToken() {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(KEY);
}

export function setToken(token) {
  window.localStorage.setItem(KEY, token);
}

export function clearToken() {
  window.localStorage.removeItem(KEY);
}
