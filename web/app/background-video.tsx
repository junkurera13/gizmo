/** Full-viewport wallpaper. Drop the file at `public/bg.mp4`. */
export function BackgroundVideo() {
  return (
    <video
      className="bg-video"
      autoPlay
      muted
      loop
      playsInline
      preload="auto"
      aria-hidden
      disablePictureInPicture
    >
      <source src="/bg.mp4" type="video/mp4" />
    </video>
  );
}
