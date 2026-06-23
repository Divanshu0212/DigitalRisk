"use client";

import { useCallback, useEffect, useState } from "react";
import RankingTable from "@/components/RankingTable";
import { getRanking, ApiError } from "@/api/client";
import { RANKING_REFRESH_MS } from "@/lib/constants";

/**
 * Dashboard (REQUIREMENTS §11.1).
 * - Fetches /ranking with pagination controls.
 * - Auto-refreshes every 30 seconds (§11.2).
 */
export default function DashboardPage() {
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(10);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const res = await getRanking({ page, limit });
      setData(res);
      setLastUpdated(new Date());
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `${err.code}: ${err.message}`
          : "Failed to load ranking."
      );
    } finally {
      setLoading(false);
    }
  }, [page, limit]);

  useEffect(() => {
    setLoading(true);
    load();
  }, [load]);

  // Auto-refresh every 30s (§11.2). Re-arms whenever dependencies change.
  useEffect(() => {
    const id = setInterval(load, RANKING_REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total_users / limit)) : 1;

  return (
    <div className="grid">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1>Leaderboard</h1>
        <div className="muted" style={{ fontSize: 12 }}>
          {lastUpdated
            ? `Updated ${lastUpdated.toLocaleTimeString()} · auto-refresh 30s`
            : "Loading…"}
        </div>
      </div>

      {error && <div className="banner error">❌ {error}</div>}

      <div className="card">
        {loading && !data ? (
          <p className="muted">Loading ranking…</p>
        ) : (
          <RankingTable ranking={data?.ranking || []} />
        )}

        <div className="pagination">
          <div className="row">
            <button
              className="secondary"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
            >
              ← Prev
            </button>
            <span className="muted" style={{ fontSize: 13 }}>
              Page {page} of {totalPages}
            </span>
            <button
              className="secondary"
              onClick={() => setPage((p) => (p < totalPages ? p + 1 : p))}
              disabled={page >= totalPages}
            >
              Next →
            </button>
          </div>
          <div className="row">
            <label style={{ margin: 0 }}>Per page</label>
            <select
              value={limit}
              onChange={(e) => {
                setLimit(Number(e.target.value));
                setPage(1);
              }}
              style={{ width: 80 }}
            >
              {[10, 20, 50].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
            <span className="muted" style={{ fontSize: 13 }}>
              {data?.total_users ?? 0} users
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
