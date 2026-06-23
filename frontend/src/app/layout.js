import { IBM_Plex_Sans, Fraunces, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import NavBar from "@/components/NavBar";

const bodyFont = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-body",
});

const headingFont = Fraunces({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-heading",
});

const monoFont = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono",
});

export const metadata = {
  title: "Transaction & Ranking Service",
  description:
    "Submit transactions, view per-user summaries, and compete on a multi-factor leaderboard.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className={`${bodyFont.variable} ${headingFont.variable} ${monoFont.variable}`}>
        <NavBar />
        <main className="container shell">{children}</main>
      </body>
    </html>
  );
}
