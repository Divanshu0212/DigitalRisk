"use client";

import { formatNumber } from "@/lib/format";

/**
 * Hover tooltip revealing the composite-score breakdown for a ranked user
 * (REQUIREMENTS §11.2). Pure CSS — no JS positioning library needed.
 */
export default function ScoreTooltip({ score, breakdown }) {
  const b = breakdown || {};
  return (
    <span className="tooltip">
      <strong>{formatNumber(score)}</strong>
      <span className="tooltip-content">
        <div>Balance <span>{formatNumber(b.balance_score)}</span></div>
        <div>Activity <span>{formatNumber(b.activity_score)}</span></div>
        <div>Diversity <span>{formatNumber(b.diversity_score)}</span></div>
      </span>
    </span>
  );
}
