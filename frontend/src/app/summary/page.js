"use client";

import { useState } from "react";
import CategoryChart from "@/components/CategoryChart";
import { getSummary, ApiError } from "@/api/client";
import { SEED_USERS } from "@/lib/constants";
import { formatCurrency, formatNumber } from "@/lib/format";

/**
 * User Summary view (REQUIREMENTS §11.1, §11.2).
 * - Enter/select a User ID.
 * - Renders headline aggregates + a CSS bar chart of the category breakdown.
 */
export default function SummaryPage() {
  const [userId, setUserId] = useState(SEED_USERS[0].user_id);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function load(id) {
    setLoading(true);
    setError(null);
    try {
      const res = await getSummary(id);
      setData(res);
    } catch (err) {
      setData(null);
      setError(
        err instanceof ApiError ? `${err.code}: ${err.message}` : "Failed to load summary."
      );
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(e) {
    e.preventDefault();
    if (userId) load(userId);
  }

  return (
    <div className="grid">
      <h1>User Summary</h1>

      <form onSubmit={onSubmit} className="card">
        <label>Select a user, or paste a UUID</label>
        <div className="row">
          <select value={userId} onChange={(e) => setUserId(e.target.value)} style={{ maxWidth: 280 }}>
            {SEED_USERS.map((u) => (
              <option key={u.user_id} value={u.user_id}>
                {u.username} — {u.user_id}
              </option>
            ))}
          </select>
          <input
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            placeholder="550e8400-..."
            style={{ flex: 1 }}
          />
          <button type="submit" disabled={loading || !userId}>
            {loading ? "Loading…" : "View Summary"}
          </button>
        </div>
      </form>

      {error && <div className="banner error">❌ {error}</div>}

      {data && (
        <div className="grid">
          <div className="card">
            <h2 style={{ textTransform: "capitalize" }}>{data.username}</h2>
            <div className="muted" style={{ fontSize: 12, marginBottom: 12 }}>
              {data.user_id}
            </div>
            <div
              className="grid"
              style={{
                gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                gap: 12,
              }}
            >
              <Stat label="Net Balance" value={formatCurrency(data.net_balance)} highlight />
              <Stat label="Total Credits" value={formatCurrency(data.total_credits)} />
              <Stat label="Total Debits" value={formatCurrency(data.total_debits)} />
              <Stat label="Transactions" value={formatNumber(data.transaction_count)} />
              <Stat label="Unique Categories" value={formatNumber(data.unique_categories)} />
              <Stat
                label="Last Activity"
                value={data.last_transaction_at ? new Date(data.last_transaction_at).toLocaleString() : "—"}
              />
            </div>
          </div>

          <div className="card">
            <h3>Category Breakdown</h3>
            <CategoryChart breakdown={data.category_breakdown} />
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, highlight }) {
  return (
    <div
      style={{
        background: "var(--panel-2)",
        borderRadius: 8,
        padding: 12,
        border: highlight ? "1px solid var(--accent)" : "1px solid var(--border)",
      }}
    >
      <div className="muted" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5 }}>
        {label}
      </div>
      <div style={{ fontSize: 18, fontWeight: 700, marginTop: 4 }}>{value}</div>
    </div>
  );
}
