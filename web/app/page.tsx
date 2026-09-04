import { Background } from "./background";
import { OddwareStrip } from "./oddware-strip";
import { SiteHeader } from "./site-header";

export default function Home() {
  return (
    <main>
      <Background />
      <SiteHeader />
      <OddwareStrip />
      <header className="hero">
        <p className="site-mark">Introducing Gizmo 1</p>
        <h1 className="hero-line">Magic you can hold.</h1>
      </header>
    </main>
  );
}
