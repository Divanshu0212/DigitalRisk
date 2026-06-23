"use client";

import { formatCurrency } from "@/lib/format";

/**
 * CSS-only horizontal bar chart for the per-user category breakdown
 * (REQUIREMENTS §11.2). No chart library — keeps the bundle tiny and the
 * render instant. Bars are scaled to the largest category total.
 */
export default function CategoryChart({ breakdown }) {
  const entries = Object.entries(breakdown || {});
  if (entries.length === 0) {
    return <p className="muted">No category data yet.</p>;
  }
  const max = Math.max(...entries.map(([, v]) => Number(v.total)), 1);

  return (
    <div className="chart-stack">
      {entries.map(([category, stat]) => {
        const total = Number(stat.total);
        const pct = Math.round((total / max) * 100);
        return (
          <div className="bar-row" key={category}>
            <span className="chart-label">{category}</span>
            <div className="bar-track" aria-hidden="true">
              <div className="bar-fill" style={{ width: `${pct}%` }} />
            </div>
            <span className="muted" style={{ fontSize: 12, textAlign: "right" }}>
              {formatCurrency(total)} · {stat.count}x
            </span>
          </div>
        );
      })}
    </div>
  );
}
