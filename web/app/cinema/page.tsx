import type { Metadata } from "next";
import { SiteHeader } from "../site-header";

export const metadata: Metadata = {
  title: "Cinema",
  description: "A private film workbench — ask a question, watch a world.",
  robots: { index: false, follow: false },
};

export default function CinemaPage() {
  const cinemaUrl =
    process.env.CINEMA_URL ??
    "https://gizmo-brain-production.up.railway.app/cinema";

  return (
    <main className="oddity-page">
      <SiteHeader />
      <h1 className="sr-only">Cinema</h1>
      <div className="oddity-frame-wrap">
        <iframe
          className="oddity-frame"
          src={`${cinemaUrl}?embedded=1`}
          title="Gizmo Cinema"
          allow="microphone; fullscreen"
          allowFullScreen
          referrerPolicy="no-referrer"
        />
      </div>
    </main>
  );
}
