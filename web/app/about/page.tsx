import type { Metadata } from "next";
import Image from "next/image";
import aboutPoster from "../../public/about.jpg";
import { SiteHeader } from "../site-header";

export const metadata: Metadata = {
  title: "About",
  description: "A rocketship for the mind.",
};

export default function AboutPage() {
  return (
    <main className="about-page">
      <SiteHeader />
      <h1 className="sr-only">About</h1>
      <div className="about-grid">
        <Image
          src={aboutPoster}
          alt="A rocketship for the mind."
          priority
          sizes="34rem"
          className="about-poster"
        />
        <article className="about-essay">
          <h2>A rocketship for the mind.</h2>
          <p>
            Every parent knows the moment. Your kid wants the screen. Not
            because the screen is good for them, but because everything on it
            was built to be wanted. Some of the brightest engineers of a
            generation spent ten years making a feed a child cannot put down. We
            call it screen time. The kids call it normal.
          </p>
          <p>
            So parents get two choices, and both are bad. Hand over the tablet,
            and watch a supercomputer become a babysitter. Or ban the
            technology, and raise a kid who meets the most powerful tool in
            human history as a stranger, at fifteen, alone, on a phone you
            didn&apos;t choose.
          </p>
          <p>We refuse both.</p>
          <p>
            Here is what everyone gets wrong about the next machine. The world
            looks at intelligence in the computer and sees something worse: a
            smarter feed, a stickier trap. We see the opposite. For the first
            time, the computer can talk back. It can listen. It can remember
            what your kid was wondering about last Tuesday and pick the thread
            back up. A machine that responds to a child is not a better
            television. It is a different thing entirely.
          </p>
          <p>It is a companion.</p>
          <p>That is Gizmo.</p>
          <p>
            Gizmo is a friend who lives in a device small enough to hold. No
            feed. No apps. No algorithm deciding what your kid watches next.
            Hold a button and talk, and Gizmo talks back. Ask him about space,
            and you are not watching a video about space. You are falling toward
            Jupiter together, the words and the pictures and the whole swirling
            storm made up on the spot, just for you, steered by whatever
            question comes next. He can be a tutor, a game master, a pair of
            eyes on a bug in the backyard, a world. Then his face again. One
            companion. Infinite rooms.
          </p>
          <p>
            The difference between brain rot and its antidote is one word:
            agency. A feed cannot be interrupted. A friend can. Gizmo answers to
            the child, never the other way around. You set the boundaries. He
            keeps the wonder.
          </p>
          <p>
            Steve Jobs called the computer a bicycle for the mind. Bicycles
            follow roads. We are building the first one that leaves the ground.
          </p>
          <p>
            This is the first computer for kids. Not a smaller phone. Not a
            safer tablet. A childhood companion, for the first generation of
            children who will grow up commanding machines instead of being fed
            by them.
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
