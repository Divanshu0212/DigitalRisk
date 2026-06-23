/**
 * Centralised constants shared between the form, summary, and table.
 * Mirrors the backend allow-list (REQUIREMENTS §4.1) so client-side
 * validation matches server-side exactly.
 */

export const ALLOWED_CATEGORIES = [
  "salary",
  "freelance",
  "investment",
  "transfer",
  "food",
  "utilities",
  "rent",
  "entertainment",
  "healthcare",
  "education",
  "other",
];

export const SEED_USERS = [
  { username: "alice", user_id: "aaa00000-0000-0000-0000-000000000001" },
  { username: "bob", user_id: "bbb00000-0000-0000-0000-0000-000000000002" },
  { username: "carol", user_id: "ccc00000-0000-0000-0000-000000000003" },
  { username: "dave", user_id: "ddd00000-0000-0000-0000-000000000004" },
  { username: "eve", user_id: "eee00000-0000-0000-0000-000000000005" },
];

// Fall back to the canonical 5 if the /users endpoint is unreachable. The
// searchable selector calls /users?search= on mount; this just guarantees a
// working default in offline/dev-first scenarios.
export const DEFAULT_USERS = SEED_USERS;

export const MAX_AMOUNT = 1_000_000;
export const RATE_LIMIT_PER_MINUTE = 20;
export const RANKING_REFRESH_MS = 30_000; // auto-refresh every 30s (§11.2)
