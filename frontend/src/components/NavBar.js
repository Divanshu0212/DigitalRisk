"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/submit", label: "Submit Transaction" },
  { href: "/summary", label: "User Summary" },
];

export default function NavBar() {
  const pathname = usePathname();
  return (
    <nav className="nav">
      <div className="brand">📊 TxnRank</div>
      <div className="links">
        {LINKS.map((l) => {
          const active =
            l.href === "/" ? pathname === "/" : pathname?.startsWith(l.href);
          return (
            <Link key={l.href} href={l.href} className={active ? "active" : ""}>
              {l.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
