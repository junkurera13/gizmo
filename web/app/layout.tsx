import type { Metadata } from "next";
import { michroma, newsreader } from "./fonts";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://oddware.xyz/gizmo"),
  title: "Gizmo",
  description: "Magic you can hold.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${michroma.variable} ${newsreader.variable}`}>
      <body>{children}</body>
    </html>
  );
}
