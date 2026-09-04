import Image from "next/image";
import bgStill from "../public/bg.png";

export function Background() {
  return (
    <div className="bg-stage" aria-hidden>
      <Image
        src={bgStill}
        alt=""
        priority
        sizes="(max-width: 700px) 160vw, 1320px"
        className="bg-still"
      />
    </div>
  );
}
