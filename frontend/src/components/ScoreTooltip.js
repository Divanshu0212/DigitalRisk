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
        <div>Balance (×0.5): {formatNumber(b.balance_score)}</div>
        <div>Activity (×0.25): {formatNumber(b.activity_score)}</div>
        <div>Diversity (×0.25): {formatNumber(b.diversity_score)}</div>
      </span>
    </span>
  );
}
