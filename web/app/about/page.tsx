import type { Metadata } from "next";
import Image from "next/image";
import aboutPoster from "../../public/about.jpg";
import { SiteHeader } from "../site-header";

export const metadata: Metadata = {
  title: "About",
  description: "A rocket ship for the mind.",
};

export default function AboutPage() {
  return (
    <main className="about-page">
      <SiteHeader />
      <h1 className="sr-only">About</h1>
      <div className="about-grid">
        <Image
          src={aboutPoster}
          alt="A rocket ship for the mind."
          priority
          sizes="(max-width: 800px) 22rem, 26rem"
          className="about-poster"
        />
        <article className="about-essay">
          <p>
            Kids got computers that could do anything, and we handed them a
            television. A supercomputer, used as a babysitter. The public looks
            at what comes next — intelligence in the machine — and sees
            something worse. We don’t.
          </p>
          <p>
            Steve Jobs called the computer a bicycle for the mind. This is the
            first time that bicycle can leave the road. Used like a tablet, that
            power flattens a child. Used like a companion, it can make them more
            human, not less.
          </p>
          <h2>Why we built Gizmo</h2>
          <p>
            We start with kids. We are building a someone they can hold. Not
            another screen. A friend.
          </p>
          <h2>What he is</h2>
          <p>
            A friend who can be anything: a tutor, a pal, a game master, a pair
            of eyes, a world. Then his face again. One companion. Infinite
            rooms.
          </p>
          <p>
            Oddware exists to bring magic back to the machine. Gizmo is the
            first one we are making real.
          </p>
        </article>
      </div>
    </main>
  );
}
