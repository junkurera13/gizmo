"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

function XLogo() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.744l7.727-8.828L1.254 2.25H8.08l4.253 5.622L18.244 2.25zm-1.161 17.52h1.833L7.084 4.126H5.117z"
      />
    </svg>
  );
}

function InstagramLogo() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect
        x="2.75"
        y="2.75"
        width="18.5"
        height="18.5"
        rx="5.25"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
      />
      <circle
        cx="12"
        cy="12"
        r="4.35"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
      />
      <circle cx="17.35" cy="6.65" r="1.15" fill="currentColor" />
    </svg>
  );
}

export function SiteHeader() {
  const onManifesto = usePathname() === "/manifesto";

  return (
    <nav className="topbar">
      <div className="nav-left">
        {onManifesto ? (
          <Link className="nav-link" href="/">
            Home
          </Link>
        ) : (
          <Link className="nav-link" href="/manifesto">
            Manifesto
          </Link>
        )}
        <a className="nav-link" href="mailto:parkjundk@gmail.com?subject=Careers">
          Careers
        </a>
        <div className="socials">
          <a
            className="nav-icon"
            href="https://x.com/oddwarelab"
            aria-label="X"
            target="_blank"
            rel="noopener noreferrer"
          >
            <XLogo />
          </a>
          <a
            className="nav-icon"
            href="https://www.instagram.com/oddwarelab/"
            aria-label="Instagram"
            target="_blank"
            rel="noopener noreferrer"
          >
            <InstagramLogo />
          </a>
        </div>
      </div>
      <Link className="interest" href="/#register">
        Register Interest
      </Link>
    </nav>
  );
}
