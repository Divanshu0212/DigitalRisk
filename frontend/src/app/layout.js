import "./globals.css";
import NavBar from "@/components/NavBar";

export const metadata = {
  title: "Transaction & Ranking Service",
  description:
    "Submit transactions, view per-user summaries, and compete on a multi-factor leaderboard.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <NavBar />
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
