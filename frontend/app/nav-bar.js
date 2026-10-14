"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { clearToken, getToken } from "../lib/auth";

export default function NavBar() {
  const [signedIn, setSignedIn] = useState(false);
  const [open, setOpen] = useState(false);
  // NavBar lives in the root layout, so client-side navigation does not remount it.
  // Re-checking on every pathname change keeps it in sync after login/register/sign-out.
  const pathname = usePathname();

  useEffect(() => {
    setSignedIn(Boolean(getToken()));
    setOpen(false);
  }, [pathname]);

  function signOut() {
    clearToken();
    window.location.href = "/login";
  }

  const link = (href, label) => (
    <Link
      href={href}
      className={pathname === href || (href !== "/" && pathname.startsWith(href + "/")) ? "active" : ""}
    >
      {label}
    </Link>
  );

  return (
    // kle-theme scopes the KLE branding to this student-facing header only.
    <div className="kle-theme">
    <header className="topbar topbar-kle">
      <div className="topbar-inner">
        <Link href="/" className="brand">
          {/* Original KLE Tech logo PNG (public/logo.png), native 400x70 aspect ratio preserved.
              The image already contains the university name/branding, so no redundant title text. */}
          <Image
            src="/logo.png"
            alt="KLE Technological University logo"
            width={400}
            height={70}
            className="kle-logo"
            priority
          />
        </Link>

        <button
          type="button"
          className="nav-toggle"
          aria-label="Toggle navigation menu"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          <span /><span /><span />
        </button>

        <nav className={`nav-links ${open ? "open" : ""}`} aria-label="Main">
          {link("/", "Home")}
          {signedIn ? (
            <>
              {link("/dashboard", "Dashboard")}
              {link("/apply", "New application")}
              <button type="button" className="btn btn-sm" onClick={signOut}>
                Sign out
              </button>
            </>
          ) : (
            <>
              {link("/login", "Sign in")}
              <Link href="/register" className="btn btn-sm">Register</Link>
            </>
          )}
        </nav>
      </div>
    </header>
    </div>
  );
}
