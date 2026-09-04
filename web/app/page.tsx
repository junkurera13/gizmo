import { Background } from "./background";
import { OddwareStrip } from "./oddware-strip";

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

export default function Home() {
  return (
    <main>
      <Background />
      <nav className="topbar">
        <div className="nav-left">
          <a className="nav-link" href="#about">
            About
          </a>
          <a className="nav-link" href="#careers">
            Careers
          </a>
          <div className="socials">
            <a className="nav-icon" href="#x" aria-label="X">
              <XLogo />
            </a>
            <a className="nav-icon" href="#instagram" aria-label="Instagram">
              <InstagramLogo />
            </a>
          </div>
        </div>
        <a className="interest" href="#register">
          Register Interest
        </a>
      </nav>
      <OddwareStrip />
      <header className="hero">
        <p className="site-mark">Introducing Gizmo 1</p>
        <h1 className="hero-line">Magic you can hold.</h1>
      </header>
    </main>
  );
}
