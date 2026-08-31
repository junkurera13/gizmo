import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Gizmo",
  description: "A wizard in a kid's pocket.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body className="bg-black">{children}</body>
    </html>
  );
}
