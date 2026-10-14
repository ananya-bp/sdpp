"use client";

import { useEffect, useState } from "react";
import { getToken } from "./auth";

// Redirects to /login when there is no token. Returns true once a token is present.
export function useRequireAuth() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    setReady(true);
  }, []);
  return ready;
}
