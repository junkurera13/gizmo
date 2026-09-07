import type { Metadata } from "next";
import { SiteHeader } from "../site-header";

export const metadata: Metadata = {
  title: "Oddity 1.0",
  description: "A private browser preview of Gizmo running OddityOS 1.",
  robots: { index: false, follow: false },
};

export default function OddityPage() {
  const emulatorUrl = process.env.ODDITY_EMULATOR_URL ?? (
    process.env.NODE_ENV === "development"
      ? "http://127.0.0.1:43148/oddity"
      : "https://gizmo-brain-production.up.railway.app/oddity"
  );

  return (
    <main className="oddity-page">
      <SiteHeader />
      <h1 className="sr-only">Oddity 1.0</h1>
      <div className="oddity-frame-wrap">
        <iframe
          className="oddity-frame"
          src={`${emulatorUrl}?embedded=1`}
          title="Gizmo running OddityOS 1"
          allow="microphone; fullscreen"
          allowFullScreen
          referrerPolicy="no-referrer"
        />
      </div>
    </main>
  );
}
