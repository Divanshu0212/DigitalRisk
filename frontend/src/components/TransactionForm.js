"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ALLOWED_CATEGORIES,
  DEFAULT_USERS,
  MAX_AMOUNT,
} from "@/lib/constants";
import { createTransaction, getUsers, ApiError } from "@/api/client";
import {
  formatCurrency,
  generateIdempotencyKey,
  parseAmount,
} from "@/lib/format";

const initialUserId = DEFAULT_USERS[0]?.user_id || "";

const EMPTY = {
  idempotency_key: generateIdempotencyKey(),
  user_id: initialUserId,
  type: "credit",
  amount: "",
  category: "salary",
  description: "",
};

/**
 * Transaction submission form (REQUIREMENTS §11.1 Submit, §11.2).
 *
 * - Pre-generates an idempotency_key on mount with a "Regenerate" button.
 * - Validates amount (positive, ≤ 1,000,000, ≤ 2 dp) and category client-side
 *   before hitting the network, matching the backend §5.1 rules.
 * - Distinct ⚠️ "Already processed" banner for duplicate (200) responses.
 * - Renders error.code + error.message from the API on failure.
 */
export default function TransactionForm() {
  const [form, setForm] = useState(EMPTY);
  const [users, setUsers] = useState(DEFAULT_USERS);
  const [selectedUser, setSelectedUser] = useState(DEFAULT_USERS[0] || null);
  const [userQuery, setUserQuery] = useState("");
  const [isUserPickerOpen, setIsUserPickerOpen] = useState(false);
  const [usersStatus, setUsersStatus] = useState("loading");
  const [status, setStatus] = useState("idle"); // idle | submitting | done
  const [result, setResult] = useState(null); // {kind:'success'|'duplicate'|'error', ...}

  const errors = useMemo(() => validate(form), [form]);

  useEffect(() => {
    let cancelled = false;

    async function loadUsers(search = "") {
      try {
        const res = await getUsers({ search, limit: 10 });
        const items = res?.users?.length ? res.users : DEFAULT_USERS;
        if (cancelled) return;
        setUsers(items);
        if (!search && !selectedUser && items[0]) {
          setSelectedUser(items[0]);
          setForm((current) => ({ ...current, user_id: items[0].user_id }));
        }
      } catch {
        if (!cancelled) {
          setUsers(DEFAULT_USERS);
        }
      } finally {
        if (!cancelled) {
          setUsersStatus("ready");
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
  }, [userQuery, selectedUser]);

  function setField(key, value) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function chooseUser(user) {
    setField("user_id", user.user_id);
    setSelectedUser(user);
    setUserQuery(`${user.username} (${user.user_id})`);
    setIsUserPickerOpen(false);
  }

  function regenerateKey() {
    setField("idempotency_key", generateIdempotencyKey());
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (Object.keys(errors).length > 0) return;
    setStatus("submitting");
    setResult(null);

    const payload = {
      idempotency_key: form.idempotency_key,
      user_id: form.user_id,
      type: form.type,
      amount: Number(form.amount),
      category: form.category,
      description: form.description || undefined,
    };

    try {
      const data = await createTransaction(payload);
      setResult({
        kind: data.is_duplicate ? "duplicate" : "success",
        data,
      });
      // If it was new, regenerate the key so a second submit can't reuse it.
      if (!data.is_duplicate) regenerateKey();
    } catch (err) {
      setResult({
        kind: "error",
        code: err instanceof ApiError ? err.code : "UNKNOWN_ERROR",
        message: err?.message || "Submission failed",
      });
    } finally {
      setStatus("done");
    }
  }

  return (
    <form onSubmit={onSubmit} className="grid">
      <ResultBanner result={result} />

      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div>
          <label>Idempotency Key</label>
          <div className="row">
            <input
              value={form.idempotency_key}
              onChange={(e) => setField("idempotency_key", e.target.value)}
            />
            <button type="button" className="secondary" onClick={regenerateKey}>
              Regenerate
            </button>
          </div>
          {errors.idempotency_key && <FieldError msg={errors.idempotency_key} />}
        </div>

        <div>
          <label>User</label>
          <div className="search-picker">
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
                {usersStatus === "loading" ? (
                  <div className="search-picker-empty">Loading users…</div>
                ) : users.length ? (
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
          <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
            Selected: {selectedUser ? `${selectedUser.username} — ${selectedUser.user_id}` : form.user_id || "None"}
          </div>
        </div>

        <div>
          <label>Type</label>
          <select
            value={form.type}
            onChange={(e) => setField("type", e.target.value)}
          >
            <option value="credit">credit</option>
            <option value="debit">debit</option>
          </select>
        </div>

        <div>
          <label>Category</label>
          <select
            value={form.category}
            onChange={(e) => setField("category", e.target.value)}
          >
            {ALLOWED_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label>Amount (max {formatCurrency(MAX_AMOUNT)})</label>
          <input
            inputMode="decimal"
            value={form.amount}
            onChange={(e) => setField("amount", e.target.value)}
            placeholder="0.00"
          />
          {errors.amount && <FieldError msg={errors.amount} />}
        </div>

        <div>
          <label>Description (optional, max 255 chars)</label>
          <input
            value={form.description}
            maxLength={255}
            onChange={(e) => setField("description", e.target.value)}
          />
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <button type="submit" disabled={status === "submitting"}>
          {status === "submitting" ? "Submitting…" : "Submit Transaction"}
        </button>
      </div>
    </form>
  );
}

function FieldError({ msg }) {
  return <div style={{ color: "var(--bad)", fontSize: 12, marginTop: 4 }}>{msg}</div>;
}

function ResultBanner({ result }) {
  if (!result) return null;
  if (result.kind === "success") {
    return (
      <div className="banner success">
        ✅ Created transaction {result.data.transaction_id.slice(0, 8)}… (
        {formatCurrency(result.data.amount)} {result.data.type} for{" "}
        {result.data.category})
      </div>
    );
  }
  if (result.kind === "duplicate") {
    return (
      <div className="banner duplicate">
        ⚠️ Already processed — original transaction{" "}
        {result.data.transaction_id.slice(0, 8)}… returned (idempotency replay).
      </div>
    );
  }
  return (
    <div className="banner error">
      ❌ <strong>{result.code}</strong>: {result.message}
    </div>
  );
}

// --- Client-side validation mirroring backend §5.1 -------------------------

function validate(form) {
  const e = {};
  if (!/^[a-zA-Z0-9\-]+$/.test(form.idempotency_key || "")) {
    e.idempotency_key = "Letters, numbers and hyphens only.";
  } else if ((form.idempotency_key || "").length < 8) {
    e.idempotency_key = "Must be at least 8 characters.";
  }
  const amount = parseAmount(form.amount);
  if (amount === null) {
    e.amount = "Positive number with at most 2 decimal places.";
  } else if (amount > MAX_AMOUNT) {
    e.amount = `Must be ≤ ${formatCurrency(MAX_AMOUNT)}.`;
  }
  return e;
}
