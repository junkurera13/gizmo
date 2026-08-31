import Image from "next/image";
import bgStill from "../public/bg.png";

export function Background() {
  return (
    <div className="bg-stage" aria-hidden>
      <Image
        src={bgStill}
        alt=""
        priority
        sizes="82vw"
        className="bg-still"
      />
    </div>
  );
}
