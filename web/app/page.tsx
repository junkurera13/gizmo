import { Background } from "./background";

export default function Home() {
  return (
    <main>
      <Background />
      <header className="hero">
        <p className="site-mark">Oddware Gizmo</p>
        <h1 className="hero-line">Magic you can hold.</h1>
      </header>
      <a className="interest" href="#register">
        Register Interest
      </a>
    </main>
  );
}
