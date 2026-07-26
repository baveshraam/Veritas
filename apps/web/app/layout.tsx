import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, IBM_Plex_Sans_Condensed } from "next/font/google";
import "./globals.css";

/* IBM Plex, self-hosted. next/font downloads at BUILD time and emits the woff2 into
 * the static export, so the deployed console makes no request to fonts.gstatic.com —
 * the same rule the rest of the platform follows about third-party runtime calls.
 *
 * Three roles, because this interface has three kinds of text: official labels
 * (condensed, the register/form voice), prose, and record identifiers. A FIR number
 * is not prose and should not be set like it. */
const sans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-sans",
  display: "swap",
});
const condensed = IBM_Plex_Sans_Condensed({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-cond",
  display: "swap",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Veritas — KSP Crime Intelligence",
  description: "Evidence-grounded investigative AI. Every answer traces to a record.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${condensed.variable} ${mono.variable}`}>
      <head>
        {/* The host sends no Cache-Control, so browsers fall back to heuristic caching
         * and pin a stale console across deploys. Say it explicitly. */}
        <meta httpEquiv="Cache-Control" content="no-cache, must-revalidate" />
      </head>
      <body>{children}</body>
    </html>
  );
}
