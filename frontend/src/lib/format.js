/** Small formatting helpers so components stay declarative. */

const currencyFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatCurrency(value) {
  const n = typeof value === "number" ? value : Number(value ?? 0);
  return currencyFmt.format(n);
}

export function formatNumber(value) {
  return new Intl.NumberFormat("en-US").format(value ?? 0);
}

/** Returns null if the input isn't parseable as a positive number. */
export function parseAmount(raw) {
  if (raw === "" || raw === null || raw === undefined) return null;
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return null;
  // Reject more than 2 decimal places (matches backend §5.1).
  const [, frac] = String(raw).split(".");
  if (frac && frac.length > 2) return null;
  return n;
}

/** Generate a fresh idempotency key conforming to ^[a-zA-Z0-9\\-]+$ (>=8 chars). */
export function generateIdempotencyKey() {
  // crypto.randomUUID() may be unavailable in very old runtimes; fall back.
  const uuid =
    typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID()
      : `key-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  return `txn-${uuid}`;
}
