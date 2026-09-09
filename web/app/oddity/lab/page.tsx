import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Oddity lab",
  description: "Private OddityOS sandbox.",
  robots: { index: false, follow: false },
};

export default function OddityLabPage() {
  const emulatorUrl =
    process.env.ODDITY_EMULATOR_URL ??
    "https://gizmo-brain-production.up.railway.app/oddity";

  return (
    <main className="oddity-lab-page">
      <h1 className="sr-only">Oddity lab</h1>
      <iframe
        className="oddity-frame"
        src={`${emulatorUrl}?lab=1`}
        title="Oddity lab"
        allow="camera; microphone; fullscreen"
        allowFullScreen
        referrerPolicy="no-referrer"
      />
    </main>
  );
}
