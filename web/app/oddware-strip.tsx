"use client";

import { useEffect, useRef, useState } from "react";

const WORD = "Oddware";
const MIN_COPIES = 16;
const SPEED_PX_PER_S = 38;

export function OddwareStrip() {
  const trackRef = useRef<HTMLSpanElement>(null);
  const [copies, setCopies] = useState(MIN_COPIES);
  const [duration, setDuration] = useState(20);

  useEffect(() => {
    const track = trackRef.current;
    if (!track) return;

    const fit = () => {
      const word = track.querySelector(".marquee-word");
      if (!(word instanceof HTMLElement)) return;

      const wordWidth = word.getBoundingClientRect().width;
      const gap = Number.parseFloat(getComputedStyle(track).gap) || 0;
      const unit = wordWidth + gap;
      if (unit <= 0) return;

      const needed = Math.max(
        MIN_COPIES,
        Math.ceil((window.innerWidth + unit) / unit) + 2,
      );
      setCopies((prev) => (prev === needed ? prev : needed));
    };

    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);

  useEffect(() => {
    const track = trackRef.current;
    if (!track) return;
    const width = track.getBoundingClientRect().width;
    if (width > 0) setDuration(width / SPEED_PX_PER_S);
  }, [copies]);

  const words = Array.from({ length: copies }, (_, i) => (
    <span className="marquee-word" key={i}>
      {WORD}
    </span>
  ));

  return (
    <div className="bottombar" aria-label="Oddware">
      <div
        className="marquee"
        aria-hidden="true"
        style={{ animationDuration: `${duration}s` }}
      >
        <span className="marquee-track" ref={trackRef}>
          {words}
        </span>
        <span className="marquee-track">{words}</span>
      </div>
    </div>
  );
}
