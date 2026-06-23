"use client";

import { useEffect, useState } from "react";
import CategoryChart from "@/components/CategoryChart";
import { getSummary, getUsers, ApiError } from "@/api/client";
import { DEFAULT_USERS } from "@/lib/constants";
import { formatCurrency, formatNumber } from "@/lib/format";

/**
 * User Summary view (REQUIREMENTS §11.1, §11.2).
 * - Enter/select a User ID.
 * - Renders headline aggregates + a CSS bar chart of the category breakdown.
 */
export default function SummaryPage() {
  const [users, setUsers] = useState(DEFAULT_USERS);
  const [selectedUser, setSelectedUser] = useState(DEFAULT_USERS[0] || null);
  const [userQuery, setUserQuery] = useState(
    DEFAULT_USERS[0] ? `${DEFAULT_USERS[0].username} (${DEFAULT_USERS[0].user_id})` : ""
  );
  const [isUserPickerOpen, setIsUserPickerOpen] = useState(false);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function loadUsers() {
      try {
        const res = await getUsers({ search: "", limit: 50 });
        const items = res?.users?.length ? res.users : DEFAULT_USERS;
        if (cancelled) return;
        setUsers(items);
        setSelectedUser((current) => current || items[0] || null);
        setUserQuery((current) => {
          if (current) return current;
          return items[0] ? `${items[0].username} (${items[0].user_id})` : "";
        });
      } catch {
        if (!cancelled) {
          setUsers(DEFAULT_USERS);
        }
      }
    }

    loadUsers();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadUsers(search = "") {
      try {
        const res = await getUsers({ search, limit: 10 });
        const items = res?.users?.length ? res.users : DEFAULT_USERS;
        if (cancelled) return;
        setUsers(items);
      } catch {
        if (!cancelled) {
          setUsers(DEFAULT_USERS);
        }
      }
    }

    const debounce = setTimeout(() => {
      loadUsers(userQuery.trim());
    }, 250);

    return () => {
      cancelled = true;
      clearTimeout(debounce);
    };
  }, [userQuery]);

  function chooseUser(user) {
    setSelectedUser(user);
    setUserQuery(`${user.username} (${user.user_id})`);
    setIsUserPickerOpen(false);
  }

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
    if (selectedUser?.user_id) load(selectedUser.user_id);
  }

  return (
    <div className="grid">
      <h1>User Summary</h1>

      <form onSubmit={onSubmit} className="card">
        <label>Search a user and select from the results</label>
        <div className="row" style={{ alignItems: "flex-start" }}>
          <div className="search-picker" style={{ flex: 1 }}>
            <input
              value={userQuery}
              onFocus={() => setIsUserPickerOpen(true)}
              onChange={(e) => {
                setUserQuery(e.target.value);
                setIsUserPickerOpen(true);
              }}
              onBlur={() => {
                window.setTimeout(() => setIsUserPickerOpen(false), 150);
              }}
              placeholder="Search users by name or UUID"
              aria-label="Search users"
            />
            {isUserPickerOpen ? (
              <div className="search-picker-results" role="listbox" aria-label="User search results">
                {users.length ? (
                  users.map((u) => (
                    <button
                      key={u.user_id}
                      type="button"
                      className="search-picker-option"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => chooseUser(u)}
                    >
                      <strong>{u.username}</strong>
                      <span>{u.user_id}</span>
                    </button>
                  ))
                ) : (
                  <div className="search-picker-empty">No matching users.</div>
                )}
              </div>
            ) : null}
          </div>
          <button type="submit" disabled={loading || !selectedUser?.user_id}>
            {loading ? "Loading…" : "View Summary"}
          </button>
        </div>
        <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          Selected: {selectedUser ? `${selectedUser.username} — ${selectedUser.user_id}` : "None"}
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
