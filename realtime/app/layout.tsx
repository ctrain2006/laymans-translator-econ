import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Real-time Economics Tutor",
  description:
    "Talk to an AI economics tutor in real time. Every explanation is grounded in a 418-term plain-English glossary.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
