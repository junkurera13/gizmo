import v2Still from "../public/v2.webp";
import { SiteHeader } from "./site-header";

export default function Home() {
  return (
    <main className="v2-page">
      <SiteHeader />
      <div className="v2-stage" aria-hidden>
        <img src={`${v2Still.src}?v=8`} alt="" className="v2-still" />
      </div>
      <svg className="v2-grain-defs" aria-hidden>
        <filter
          id="text-grain"
          x="-8%"
          y="-30%"
          width="116%"
          height="160%"
          colorInterpolationFilters="sRGB"
        >
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.85"
            numOctaves="3"
            stitchTiles="stitch"
            result="noise"
          />
          <feColorMatrix
            in="noise"
            type="matrix"
            values="0 0 0 0 0.72  0 0 0 0 0.72  0 0 0 0 0.72  0 0 0 0.18 0"
            result="speck"
          />
          <feComposite in="speck" in2="SourceAlpha" operator="in" result="grain" />
          <feBlend in="SourceGraphic" in2="grain" mode="multiply" />
        </filter>
      </svg>
      <header className="v2-caption">
        <h1 className="hero-line" style={{ filter: "url(#text-grain)" }}>
          Magic you can hold.
        </h1>
        <p className="site-mark v2-eyebrow" style={{ filter: "url(#text-grain)" }}>
          Oddware Gizmo 1
        </p>
      </header>
    </main>
  );
}
