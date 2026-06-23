"use client";

import { formatCurrency, formatNumber } from "@/lib/format";
import ScoreTooltip from "./ScoreTooltip";

function RankBadge({ rank }) {
  const cls = rank === 1 ? "top1" : rank === 2 ? "top2" : rank === 3 ? "top3" : "";
  return <span className={`rank-badge ${cls}`}>{rank}</span>;
}

/**
 * Leaderboard table (REQUIREMENTS §11.1 Dashboard).
 * The composite_score cell hosts the ScoreTooltip hover (§11.2).
 */
export default function RankingTable({ ranking }) {
  if (!ranking || ranking.length === 0) {
    return <p className="muted">No ranked users yet. Rankings will appear once transactions are submitted.</p>;
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <table>
        <thead>
          <tr>
            <th>Rank</th>
            <th>User</th>
            <th>Net Balance</th>
            <th>Transactions</th>
            <th>Categories</th>
            <th>Score</th>
          </tr>
        </thead>
        <tbody>
          {ranking.map((u) => (
            <tr key={u.user_id}>
              <td>
                <RankBadge rank={u.rank} />
              </td>
              <td>
                <strong className="user-name">{u.username}</strong>
                <div className="muted" style={{ fontSize: 11, fontFamily: "var(--font-mono)" }}>
                  {u.user_id.slice(0, 8)}…
                </div>
              </td>
              <td>{formatCurrency(u.net_balance)}</td>
              <td>{formatNumber(u.transaction_count)}</td>
              <td>{formatNumber(u.unique_categories)}</td>
              <td>
                <ScoreTooltip score={u.composite_score} breakdown={u.score_breakdown} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
